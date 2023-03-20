"""
Script  to train updated CameraTrapDetectoR model
"""

# Imports
import os
import torch
from utils.data_process import class_range, existing_images, \
    orient_boxes, format_vars, split_df
from utils import dicts
import pandas as pd

from utils.data_setload import DetectDataset, get_class_weights
from torch.utils.data import DataLoader

from utils.hyperparameters import get_anchors, get_transforms
from models.backbones import load_fasterrcnn

from torch.optim import SGD, lr_scheduler
from utils.hyperparameters import get_lr

import time
from datetime import timedelta
from tqdm import tqdm
import copy
from utils.checkpoints import write_args, \
    create_checkpoint, save_checkpoint


#######
## -- Prepare System and Data for Model Training
#######

# Set location
if os.name == 'posix':
    local = False
else:
    local = True

# Set paths
if local:
    IMAGE_ROOT = 'G:/!ML_training_datasets/!VarifiedPhotos'
    os.chdir("C:/Users/Amira.Burns/OneDrive - USDA/Projects/CameraTrapDetectoR")
else:
    IMAGE_ROOT = "/90daydata/cameratrapdetector/trainimages"
    os.chdir('/project/cameratrapdetector')

# set device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(device)

# determine if resuming training from existing checkpoint
resume = False

# model setup if resuming training
if resume:
    # set output path
    output_path = "./output/fasterRCNN_resnet_20230221_1612/"

    # load datasets
    train_df = pd.read_csv(output_path + "train_df.csv")
    val_df = pd.read_csv(output_path + "val_df.csv")
    test_df = pd.read_csv(output_path + "test_df.csv")

    # open model arguments file
    with open(output_path + 'model_args.txt') as f:
        model_args = {k: v for line in f for (k, v) in [line.strip().split(":")]}

    # load model checkpoint
    checkpoint_path = output_path + "checkpoint_24epochs.pth"
    checkpoint = torch.load(checkpoint_path, map_location=device)

    #load model type
    model_type = checkpoint['model_type']

    # define label dictionaries
    label2target = checkpoint['label2target']
    target2label = {t: l for l, t in label2target.items()}

    # define image dimensions
    w = int(model_args['image width'])
    h = int(model_args['image height'])

    # define data augmentation pipelines
    transforms = model_args['data augmentations']
    train_transform, val_transform = get_transforms(transforms=transforms, w=w, h=h)

    # load Pytorch datasets
    train_ds = DetectDataset(df=train_df, image_dir=IMAGE_ROOT, w=w, h=h,
                             label2target=label2target, transform=train_transform)
    val_ds = DetectDataset(df=val_df, image_dir=IMAGE_ROOT, w=w, h=h,
                           label2target=label2target, transform=val_transform)

    # define anchor generator
    anchor_sizes, anchor_gen = get_anchors(h=h)
    assert anchor_sizes == tuple(eval(model_args['anchor box sizes'])), "Anchor box sizes not consistent."

    # initiate model
    cnn_backbone = model_args['backbone']
    num_classes = checkpoint['num_classes']
    model = load_fasterrcnn(cnn_backbone, num_classes, anchor_gen)

    # load current model weights from checkpoint
    model.load_state_dict(checkpoint['state_dict'])
    model.to(device)
    params = [p for p in model.parameters() if p.requires_grad]

    # define total epochs
    num_epochs = 50
    assert num_epochs > checkpoint['epoch'], "Model already trained for total epochs requested."

    # load batch size
    batch_size = int(model_args['batch size'])
    batch_size_org = batch_size

    # boolean to use gradient accumulation
    use_grad = True

    # set denominator if using gradient accumulation
    if use_grad:
        # set number of gradients to accumulate before updating weights
        grad_accumulation = 8
        # effective batch size = batch_size * grad_accumulation
        batch_size = batch_size_org // grad_accumulation

    # set up class weights
    sampler = get_class_weights(train_df)

    # define dataloaders
    train_loader = DataLoader(train_ds, batch_size=batch_size, collate_fn=train_ds.collate_fn,
                              drop_last=True, sampler=sampler)
    # do not oversample for validation, just for training
    val_loader = DataLoader(val_ds, batch_size=batch_size, collate_fn=train_ds.collate_fn, drop_last=True)

    # load hyperparameters
    lr = checkpoint['current_lr']
    wd = float(model_args['weight decay'])
    momentum = 0.9

    # load optimizer
    optim = 'SGD'
    optimizer = SGD(params=params, lr=lr, weight_decay=wd, momentum=momentum)
    optimizer.load_state_dict(checkpoint['optimizer'])

    # load lr scheduler
    lr_scheduler = lr_scheduler.ReduceLROnPlateau(optimizer, patience=2, factor=0.5)



# model setup for new training
else:
    # Set model type: options = 'general', 'family', 'species', 'pig_only'
    model_type = 'species'

    max_per_class, min_per_class = class_range(model_type)

    # load annotations
    df = pd.read_csv("./labels/varified.bounding.boxes_for.training.final.2022-10-19.csv")

    # prune df to existing images
    df = existing_images(df, IMAGE_ROOT)

    # confirm all bbox coordinates correspond to UL, LR corners
    df = orient_boxes(df)

    # format df
    df = format_vars(df)

    # create dictionary - create the dict corresponding to model type
    df, label2target, columns2stratify = dicts.spec_dict(df, max_per_class, min_per_class)

    # reverse dictionary to read into pytorch
    target2label = {t: l for l, t in label2target.items()}

    # define number of classes
    num_classes = max(label2target.values()) + 1

    # split df into train/val/test sets
    train_df, val_df, test_df = split_df(df, columns2stratify)

    # set image dimensions for training
    # TODO: determine ideal training w and h
    w = 408
    h = 307

    # define data augmentation pipelines
    # note augmentations as a string to save in model arguments
    transforms = 'shear, rotate, huesat, brightcont, safecrop, hflip'

    train_transform, val_transform = get_transforms(transforms, w, h)

    # Load PyTorch Datasets
    train_ds = DetectDataset(df=train_df, image_dir=IMAGE_ROOT, w=w, h=h,
                             label2target=label2target, transform=train_transform)
    val_ds = DetectDataset(df=val_df, image_dir=IMAGE_ROOT, w=w, h=h,
                           label2target=label2target, transform=val_transform)

    # define anchor boxes based on image size
    anchor_sizes, anchor_gen = get_anchors(h=h)

    # define model backbone
    cnn_backbone = 'resnet'

    # initialize model
    model = load_fasterrcnn(cnn_backbone, num_classes, anchor_gen).to(device)
    params = [p for p in model.parameters() if p.requires_grad]

    # define number of training epochs
    num_epochs = 50

    # define batch size
    batch_size = 32
    batch_size_org = batch_size

    # boolean to use gradient accumulation
    use_grad = True

    # set denominator if using gradient accumulation
    if use_grad:
        # set number of gradients to accumulate before updating weights
        grad_accumulation = 8
        # effective batch size = batch_size * grad_accumulation
        batch_size = batch_size_org // grad_accumulation

    # set up class weights
    sampler = get_class_weights(train_df)

    # define dataloaders
    train_loader = DataLoader(train_ds, batch_size=batch_size, collate_fn=train_ds.collate_fn,
                              drop_last=True, sampler=sampler)
    # do not oversample for validation, just for training
    val_loader = DataLoader(val_ds, batch_size=batch_size, collate_fn=train_ds.collate_fn, drop_last=True)

    # define starting lr, wd, momentum
    #TODO: review training results to confirm these
    lr = 0.01
    wd = 0.001
    momentum = 0.9

    # load optimizer
    #TODO: create function to choose this based on optim
    optim = 'SGD'
    optimizer = SGD(params=params, lr=lr, weight_decay=wd, momentum=momentum)

    # set learning rate scheduler
    lr_scheduler = lr_scheduler.ReduceLROnPlateau(optimizer, patience=2, factor=0.5)

    # make output directory and filepath
    output_path = "./output/" + "fasterRCNN_" + cnn_backbone + "_" + \
                  time.strftime("%Y%m%d") + "_" + time.strftime("%H%M") + "/"
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    # write model args to text file
    write_args(cnn_backbone, w, h, transforms, anchor_sizes, batch_size_org, optim, lr, wd, lr_scheduler, output_path)

    # Get database of training data attributes by site, class
    db_full, db_simple = dicts.train_database(df=train_df)

    # write datasets to csv
    train_df.to_csv(output_path + "train_df.csv")
    val_df.to_csv(output_path + "val_df.csv")
    test_df.to_csv(output_path + "test_df.csv")
    db_full.to_csv(output_path + "db_full.csv")
    db_simple.to_csv(output_path + "db_simple.csv")

#######
## -- Train the Model
#######


# define starting weights
# TODO: incorporate function for loading existing model weights when training iteratively
best_model_wts = copy.deepcopy(model.state_dict())

if resume:
    # load existing losses
    best_loss = checkpoint['best_loss']
    loss_history = checkpoint['loss_history']

    # load training time
    training_time = checkpoint['training_time']

    # load current epoch
    epoch = checkpoint['epoch']

else:
    # define starting loss
    best_loss = float('inf')

    # create empty list to save train/val losses
    loss_history = {
        'train': [],
        'val': []
    }

    # create empty list to save training time per epoch
    training_time = []

    # define starting epoch
    epoch = range(num_epochs)[0]

# training/validation loop
for epoch in range(epoch, num_epochs):
    # record start time
    t_start = time.time()

    # set learning rate
    current_lr = get_lr(optimizer)

    # print epoch info
    print('Epoch {}, current lr={}'.format(epoch + 1, current_lr))

    ## -- TRAIN PASS
    # initialize training pass
    model.train()
    running_loss = 0.0

    # loop through train loader
    for batch_idx, (images, targets) in enumerate(tqdm(train_loader)):
        # send data to device
        images = list(image.to(device) for image in images)
        targets = [{'boxes': t['boxes'].to(device), 'labels': t['labels'].to(device)} for t in targets]

        # forward pass, calculate losses
        losses = model(images, targets)
        loss = sum(loss for loss in losses.values())

        # TODO: determine if optimizer.zero_grad() needs to move
        if use_grad:
            # normalize loss to account for batch accumulation
            loss = loss / grad_accumulation
            # backward pass
            loss.backward()
            # optimizer step every x=grad_accumulation batches
            if ((batch_idx + 1) % grad_accumulation == 0) or (batch_idx + 1 == len(train_loader)):
                optimizer.step()
                optimizer.zero_grad()
                print(f'Batch {batch_idx} / {len(train_loader)} | Train Loss: {loss:.4f}')

        else:
            # backward pass
            loss.backward()
            # optimizer step
            optimizer.step()
            # reset gradients
            optimizer.zero_grad()
            print(f'Batch {batch_idx} / {len(train_loader)} | Train Loss: {loss:.4f}')

        # update loss
        running_loss += loss.item()

    # average loss across entire epoch
    epoch_train_loss = running_loss / len(train_loader)

    # record training loss
    loss_history['train'].append(epoch_train_loss)

    ## -- VALIDATION PASS

    # initialize validation pass, validation loss
    model.train(False)
    running_val_loss = 0.0

    # loop through val loader
    with torch.no_grad():
        for batch_idx, (images, targets) in enumerate(tqdm(val_loader)):
            model.train()  # obtain losses without defining forward method
            # move to device
            images = list(image.to(device) for image in images)
            targets = [{k: v.to(device) for k, v in t.items()} for t in targets]

            # collect losses
            val_losses = model(images, targets)
            val_loss = sum(loss for loss in val_losses.values())

            if use_grad:
                # normalize loss based on gradient accumulation
                val_loss = val_loss / grad_accumulation
                if ((batch_idx + 1) % grad_accumulation == 0) or (batch_idx + 1 == len(val_loader)):
                    # reset gradients
                    optimizer.zero_grad()
                    print(f'Batch {batch_idx} / {len(val_loader)} | Val Loss: {val_loss:.4f}')

            else:
                # reset gradients
                optimizer.zero_grad()
                print(f'Batch {batch_idx} / {len(val_loader)} | Val Loss: {val_loss:.4f}')

            # update loss
            running_val_loss += float(val_loss)

    # average val loss across the entire epoch
    epoch_val_loss = running_val_loss / len(val_loader)

    # record validation loss
    loss_history['val'].append(epoch_val_loss)

    ## -- UPDATE MODEL

    # record model weights based on val_loss
    if val_loss < best_loss:
        # update best loss
        best_loss = val_loss
        # update model weights
        best_model_wts = copy.deepcopy(model.state_dict())

    # adjust learning rate
    lr_scheduler.step(val_loss)

    # load best model weights if current epoch did not produce best weights
    if current_lr != get_lr(optimizer):
        model.load_state_dict(best_model_wts)

    # calculate training time per epoch
    elapsed = time.time() - t_start
    elapsed = str(timedelta(seconds=elapsed))
    training_time.append(elapsed)

    # save model state
    checkpoint = create_checkpoint(model, optimizer, epoch, current_lr, loss_history,
                                   best_loss, model_type, num_classes, label2target, training_time)
    checkpoint_file = output_path + "checkpoint_" + str(epoch + 1) + "epochs.pth"
    save_checkpoint(checkpoint, checkpoint_file)

    print('Model trained for {} epochs'.format(epoch + 1))




