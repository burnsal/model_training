# CameraTrapDetectoR Model Training

This repository contains the Python code used to train new versions of the CameraTrapDetectoR models. 

# CameraTrapDetectoR Model Deployment

## Installation

### 1. System Prerequisites

You will need [Anaconda](https://docs.conda.io/projects/miniconda/en/latest/) and [Git](https://git-scm.com/download/win) installations to set up your model environment. If your environment can access a [Pytorch-compatible GPU](https://pytorch.org/get-started/locally/), make sure you have an updated [NVIDIA driver](https://www.nvidia.com/download/index.aspx) installed as well.

### 2. Clone Git Repository    

Open your Anaconda prompt and navigate to the directory where you'd like to store your project. Clone this repository:    

```batch
cd /path/to/project/dir
git clone https://github.com/CameraTrapDetectoR/model_training.git
```

### 3. Create Python Environment

Navigate into the model_training directory and locate a file called *deploy_model_env.yml*. This file contains the setup info and required Python packages needed to run the models. You can create your environment using the YAML file:   
```batch
cd model_training
conda env create -n ctd-deploy-model -f deploy_model_env.yml
```
or you can manually create a Python environment and install the listed packages using the package manager of your choosing.    

This step may take a while! Go get a cup of coffee or a yummy snack, and start [downloading the models](https://github.com/CameraTrapDetectoR/model_training/blob/main/README.md#4-download-models) while you wait.  

### 4. Download Models

## Use


