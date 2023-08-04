# Copyright (c) 2020, NVIDIA CORPORATION.  All rights reserved.
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import os
import random
from distutils.util import strtobool

import numpy as np
import copy
import torch
import yaml
import argparse
#from isaacgym import gymapi, gymutil


def set_np_formatting():
    np.set_printoptions(edgeitems=30, infstr='inf',
                        linewidth=4000, nanstr='nan', precision=2,
                        suppress=False, threshold=10000, formatter=None)


def warn_task_name():
    raise Exception(
        "Unrecognized task!")

def warn_algorithm_name():
    raise Exception(
                "Unrecognized algorithm!\nAlgorithm should be one of: [ppo, happo, hatrpo, mappo]")


def set_seed(seed, torch_deterministic=False):
    if seed == -1 and torch_deterministic:
        seed = 42
    elif seed == -1:
        seed = np.random.randint(0, 10000)

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

    if torch_deterministic:
        os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.set_deterministic(True)
    else:
        torch.backends.cudnn.benchmark = True
        torch.backends.cudnn.deterministic = False

    return seed

def parse_sim_params(args, cfg, cfg_train):
    # initialize sim
    try:
        from isaacgym import gymapi, gymutil
    except ImportError:
        raise Exception("Please install isaacgym to run ShadowHand tasks!")
    sim_params = gymapi.SimParams()
    sim_params.dt = 1./60.
    sim_params.num_client_threads = args.slices

    if args.physics_engine == gymapi.SIM_FLEX:
        if args.device != "cpu":
            print("WARNING: Using Flex with GPU instead of PHYSX!")
        sim_params.flex.shape_collision_margin = 0.01
        sim_params.flex.num_outer_iterations = 4
        sim_params.flex.num_inner_iterations = 10
    elif args.physics_engine == gymapi.SIM_PHYSX:
        sim_params.physx.solver_type = 1
        sim_params.physx.num_position_iterations = 4
        sim_params.physx.num_velocity_iterations = 0
        sim_params.physx.num_threads = 4
        sim_params.physx.use_gpu = args.use_gpu
        sim_params.physx.num_subscenes = args.subscenes
        sim_params.physx.max_gpu_contact_pairs = 8 * 1024 * 1024

    sim_params.use_gpu_pipeline = args.use_gpu_pipeline
    sim_params.physx.use_gpu = args.use_gpu

    # if sim options are provided in cfg, parse them and update/override above:
    if "sim" in cfg:
        gymutil.parse_sim_config(cfg["sim"], sim_params)

    # Override num_threads if passed on the command line
    if args.physics_engine == gymapi.SIM_PHYSX and args.num_threads > 0:
        sim_params.physx.num_threads = args.num_threads

    return sim_params


def get_args():

    # Define custom parameters
    custom_parameters = [
        {"name": "--use-eval", "type": lambda x: bool(strtobool(x)), "default": False, "help": "Use evaluation environment for testing"},
        {"name": "--task", "type": str, "default": "MujocoVelocity", "help": "The task to run"},
        {"name": "--agent-conf", "type": str, "default": "2x4", "help": "The agent configuration"},
        {"name": "--scenario", "type": str, "default": "Ant", "help": "The scenario"},
        {"name": "--experiment", "type": str, "default": "Base", "help": "Experiment name. If used with --metadata flag an additional information about physics engine, sim device, pipeline and domain randomization will be added to the name"},
        {"name": "--seed", "type": int, "default":0, "help": "Random seed"},
        {"name": "--algo", "type": str, "default": "happo", "help": "Choose an algorithm"},
        {"name": "--model-dir", "type": str, "default": "", "help": "Choose a model dir"},
        {"name": "--safety-bound", "type": float, "default": 25.0, "help": "cost_lim"},
        {"name": "--device", "type": str, "default": "cpu", "help": "The device to run the model on"},
        {"name": "--device-id", "type": int, "default": 0, "help": "The device id to run the model on"},
        {"name": "--write-terminal", "type": lambda x: bool(strtobool(x)), "default": True, "help": "Toggles terminal logging"},
        {"name": "--headless", "type": lambda x: bool(strtobool(x)), "default": False, "help": "Toggles headless mode"},
    ]
    # Create argument parser
    parser = argparse.ArgumentParser(description="RL Policy")
    issac_parameters = copy.deepcopy(custom_parameters)
    for param in custom_parameters:
        param_name = param.pop("name")
        parser.add_argument(param_name, **param)

    # Parse arguments

    args = parser.parse_args()

    if args.task in ["ShadowHandOver", "ShadowHandCatchUnderarm"]:
        try:
            from isaacgym import gymutil
        except ImportError:
            raise Exception("Please install isaacgym to run ShadowHand tasks!")
        args = gymutil.parse_arguments(description="RL Policy", custom_parameters=issac_parameters)
        args.device = args.sim_device_type if args.use_gpu_pipeline else 'cpu'
    config_map = {
        "ShadowHandOver": "shadow_hand_over",
        "ShadowHandCatchUnderarm": "shadow_hand_catch_underarm",
    }
    cfg_train_path = "marl_cfg/{}/config.yaml".format(args.algo)
    with open(os.path.join(os.getcwd(), cfg_train_path), 'r') as f:
        cfg_train = yaml.load(f, Loader=yaml.SafeLoader)
        if args.task == "MujocoVelocity":
            cfg_train.update(cfg_train.get("mamujoco"))
    cfg_train["use_eval"] = args.use_eval
    cfg_train["safety_bound"]=args.safety_bound
    cfg_train["algorithm_name"]=args.algo
    cfg_train["device"] = args.device + ":" + str(args.device_id)

    if args.task == "MujocoVelocity":
        env_name = "Safety"+args.agent_conf+args.scenario+"Velocity-v0"
    else:
        env_name = args.task
    cfg_train['log_dir']="./runs/"+args.experiment+'/'+env_name+'/'+args.algo
    cfg_env={}
    if args.task in ["ShadowHandOver", "ShadowHandCatchUnderarm"]:
        cfg_env_path = "marl_cfg/{}.yaml".format(config_map[args.task])
        with open(os.path.join(os.getcwd(), cfg_env_path), 'r') as f:
            cfg_env = yaml.load(f, Loader=yaml.SafeLoader)
            cfg_env["name"] = args.task
            if "task" in cfg_env:
                if "randomize" not in cfg_env["task"]:
                    cfg_env["task"]["randomize"] = args.randomize
                else:
                    cfg_env["task"]["randomize"] = False
            else:
                cfg_env["task"] = {"randomize": False}
    elif args.task == "MujocoVelocity":
        pass
    else:
        warn_task_name()

    return args, cfg_env, cfg_train
