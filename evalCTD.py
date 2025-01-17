"""
Script to deploy CameraTrapDetectoR model on out of sample data
"""

import os
import torch
from PIL import ImageFile
import numpy as np
import pandas as pd
import cv2


from utils.hyperparameters import get_anchors
from models.backbones import load_fasterrcnn
from tqdm import tqdm
from torchvision.ops import nms

from utils.post_process import format_evals, plot_image
from collections import Counter


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
    IMAGE_ROOT = 'path/to/out_of_sample/images'
    os.chdir("path/to/Projects/CameraTrapDetectoR")
else:
    IMAGE_ROOT = "/path/to/cameratrapdetector/outofsample/images"
    os.chdir('/project/cameratrapdetector')

# set device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(device)

# allow truncated images to load
ImageFile.LOAD_TRUNCATED_IMAGES = True

# set path to model run being deployed
model_path = "./output/general_v2/"

# open model arguments file
with open(model_path + 'model_args.txt') as f:
    model_args = {k: v for line in f for (k, v) in [line.strip().split(":")]}
model_args['image width'] = int(model_args['image width'])
model_args['image height'] = int(model_args['image height'])
model_args['anchor box sizes'] = tuple(eval(model_args['anchor box sizes']))
cnn_backbone = model_args['backbone']

# define image dimensions
w = model_args['image width']
h = model_args['image height']

# load model checkpoint
checkpoint_path = model_path + "checkpoint_50epochs.pth"
checkpoint = torch.load(checkpoint_path, map_location=device)

# load model type
model_type = checkpoint['model_type']

# load dictionaries
label2target = checkpoint['label2target']
target2label = {t: l for l, t in label2target.items()}

# make sure the empty entry is at the beginning of the dictionary
keys = sorted(target2label.keys())
vals = [target2label[k] for k in keys]
target2label = dict(zip(keys, vals))

# reload anchor generator
anchor_sizes, anchor_gen = get_anchors(h=h)

# initiate model
cnn_backbone = 'resnet'
num_classes = checkpoint['num_classes']
model = load_fasterrcnn(cnn_backbone, num_classes, anchor_gen)

# load model weights
model.load_state_dict(checkpoint['state_dict'])
model.to(device)

# set image directory
IMAGE_PATH = './path/to/image/dataset'

# load image names
image_infos = [os.path.join(dp, f).replace(os.sep, '/') for dp, dn, fn in os.walk(IMAGE_PATH) for f in fn if
               os.path.splitext(f)[1].lower() == '.jpg']

image_infos = [f for f in image_infos if not 'prediction_plots' in f]

# define checkpoint path
chkpt_pth = IMAGE_PATH + '/ProjectName_' + model_type + '_pred_checkpoint.csv'

# Create output dir to hold plotted images
plot_images = False
if plot_images == True:
    PRED_PATH = IMAGE_PATH + '/' + model_type + '_prediction_plots/'
    if os.path.exists(PRED_PATH) == False:
        os.mkdir(PRED_PATH)

#######
## -- Evaluate Model on Test Data
#######

# create placeholder for predictions
pred_df = pd.DataFrame(columns=['filename', 'file_id', 'class_name', 'confidence', 'bbox'])

resume_from_checkpoint = True
if resume_from_checkpoint == True:
    # load checkpoint file
    pred_checkpoint = pd.read_csv(chkpt_pth)

    # turn pred_checkpoint into list of dataframes and add to pred_df
    pred_df = pd.concat([pred_df, pred_checkpoint], ignore_index=True)

    # filter through image infos and update list to images not in pred_df
    also_rans = pred_df.filename.unique().tolist()
    image_infos = [x for x in image_infos if x not in also_rans]

# deploy model
count = 0
with torch.no_grad():
    model.eval()
    for i in tqdm(range(len(image_infos))):
        try:
            # set image path
            img_path = image_infos[i]
            # open image
            img_org = cv2.imread(img_path)
            # reformat color channels
            img = cv2.cvtColor(img_org, cv2.COLOR_BGR2RGB)
            # resize image so bboxes can also be converted
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            img = img.astype(np.float32) / 255.
            # convert array to tensor
            img = torch.from_numpy(img)
            # shift channels to be compatible with model input
            image = img.permute(2, 0, 1)
            image = image.unsqueeze_(0)
            # send input to CUDA if available
            image = image.to(device)

            # run input through the model
            output = model(image)[0]

            # extract prediction bboxes, labels, scores above score_thresh
            # format prediction data
            bbs = output['boxes'].cpu().detach()
            labels = output['labels'].cpu().detach()
            confs = output['scores'].cpu().detach()

            # id indicies of tensors to include in evaluation
            idx = torch.where(confs > 0.01)

            # filter to predictions that meet the threshold
            bbs, labels, confs = [tensor[idx] for tensor in [bbs, labels, confs]]

            # perform non-maximum suppression on remaining predictions
            ixs = nms(bbs, confs, iou_threshold=0.5)

            bbs, confs, labels = [tensor[ixs] for tensor in [bbs, confs, labels]]

            # normalize bboxes
            norms = torch.tensor([1/w, 1/h, 1/w, 1/h])
            bbs *= norms

            # format predictions
            bbs = bbs.tolist()
            confs = confs.tolist()
            labels = labels.tolist()
            class_names = [target2label[a] for a in labels]

            if len(bbs) == 0:
                pred_df_i = pd.DataFrame({
                    'filename': image_infos[i],
                    'file_id': image_infos[i][:-4],
                    'class_name': 'empty',
                    'confidence': 1,
                    'bbox': [[0, 0, 0, 0]]
                })
            else:
                pred_df_i = pd.DataFrame({
                    'filename': image_infos[i],
                    'file_id': image_infos[i][:-4],
                    'class_name': class_names,
                    'confidence': confs,
                    'bbox': bbs
                })

            # plot image if argument selected
            if plot_images & (len(bbs)>0):
                plot_image(img_org, bbs, confs, class_names, img_path, IMAGE_PATH, PRED_PATH)


        except Exception as err:
            pred_df_i = pd.DataFrame({
                'filename': image_infos[i],
                'file_id': image_infos[i][:-4],
                'class_name': "Image error",
                'confidence': 0,
                'bbox': [[0, 0, 0, 0]]
            })
            pass

        # add image predictions to existing df
        pred_df = pd.concat([pred_df, pred_df_i], ignore_index=True)

        # save results every 10 images
        count += 1
        if count % 10 == 0:
            # save to checkpoint
            pred_df.to_csv(chkpt_pth, index=False)

# save prediction and target dfs to csv
# pred_df.to_csv(IMAGE_ROOT + "_" + model_type + '_results_raw.csv', index=False)
pred_df.to_csv(IMAGE_PATH + '/TableMtn_' + model_type + '_results_raw.csv', index=False)

# remove checkpoint file
os.remove(chkpt_pth)

#######
## -- Post Processing
#######

# # Drop bboxes
pred_df = pred_df.drop(['bbox'], axis=1)

# # Rename and remove columns
pred_df = pred_df.rename(columns={'filename': 'file_path', 'class_name': 'prediction'}).drop(['file_id'], axis=1)

# remove prefix from filepath
pred_df['file_path'] = pred_df.file_path.str.replace("/unwanted/dir/info/", "")

# # split image name to extract site, camera, date info
image_parts = pred_df.file_path.str.rsplit("/", n=4, expand=True)
#
# site name
pred_df['project'] = image_parts[0]
#
# # camera name
pred_df['cam_id'] = image_parts[1]
#
# timestamp
pred_df['collection_date'] = image_parts[2]

# image name
pred_df['image_name'] = image_parts[3]
#
# # get prediction counts for each image
cts = Counter(pred_df['file_path']).items()
pred_counts = pd.DataFrame.from_dict(cts)
pred_counts.columns = ['file_path', 'count']
pred_df = pred_df.merge(pred_counts, on='file_path', how='left')

# # separate images with one prediction and images with >1 predictions
single_preds = pred_df[pred_df['count'] == 1]
multi_preds = pred_df[pred_df['count'] > 1]

# # format single preds
single_preds.loc[single_preds['prediction'] == 'empty', 'count'] = 0
#
# # drop counts from multi_preds
multi_preds = multi_preds.drop(['count'], axis=1)

# # get new counts based on image + predicted class
multi_cts = multi_preds.groupby(['file_path', 'prediction'])['prediction'].count().reset_index(name='count')
#
# # join multi_preds to new counts
multi_preds = multi_preds.merge(multi_cts, on=['file_path', 'prediction'], how='left', copy=False)
#
# # filter multi_preds to one prediction per image + class group - take highest confidence
filtr_preds = multi_preds.groupby(['file_path', 'prediction']).apply(
    lambda x: x[x['confidence'] == max(x['confidence'])])

# join filtered multi_preds to single_preds
preds = pd.concat([single_preds, filtr_preds], ignore_index=True).sort_values(['file_path'])

# reorder image_name column
preds = preds.loc[:, ['file_path', 'project', 'cam_id', 'image_name',
                      'collection_date', 'prediction', 'confidence', 'count']]

# add columns for manual review: true_class, true_count, comments
preds['true_class'] = ""
preds['true_count'] = ""
preds['comments'] = ""

# save with new formatted name
# preds.to_csv(IMAGE_PATH + "_" + model_type + '_results_formatted.csv', index=False)
preds.to_csv(IMAGE_PATH + "/ProjectName_" + model_type + '_results_formatted.csv',
             index=False)

# TODO: write predictions to image metadata



# END
