import time
import torch
from torch.backends import cudnn
from matplotlib import colors
from backbone import HybridNetsBackbone
import cv2
import numpy as np
import glob
from utils.utils import preprocess, invert_affine, postprocess, STANDARD_COLORS, standard_to_bgr, get_index_label, plot_one_box, BBoxTransform, ClipBoxes

compound_coef = 3
force_input_size = None  # set None to use default size
img_path = [path for path in glob.glob('./demo_imgs/*.jpg')]
img_path = [img_path[0]]  # demo with 1 image

# replace this part with your project's anchor config
anchor_ratios = [(0.62, 1.58), (1.0, 1.0), (1.58, 0.62)]
anchor_scales = [2**0, 2**0.70, 2**1.32]

threshold = 0.5
iou_threshold = 0.3

use_cuda = True
use_float16 = False
cudnn.fastest = True
cudnn.benchmark = True

obj_list= ['car']


color_list = standard_to_bgr(STANDARD_COLORS)
# tf bilinear interpolation is different from any other's, just make do
input_sizes = [512, 640, 768, 640, 1024, 1280, 1280, 1536, 1536]
input_size = input_sizes[compound_coef] if force_input_size is None else force_input_size
ori_imgs, framed_imgs, framed_metas = preprocess(img_path, max_size=input_size)
# ori_img = ori_imgs[0]

if use_cuda:
    x = torch.stack([torch.from_numpy(fi).cuda() for fi in framed_imgs], 0)
else:
    x = torch.stack([torch.from_numpy(fi) for fi in framed_imgs], 0)

x = x.to(torch.float32 if not use_float16 else torch.float16).permute(0, 3, 1, 2)
print(x.shape)

model = HybridNetsBackbone(compound_coef=compound_coef, num_classes=len(obj_list),
                             ratios=anchor_ratios, scales=anchor_scales, seg_classes=2)
try:
    model.load_state_dict(torch.load('weights/weight97.pth', map_location='cpu'))
except:
    model.load_state_dict(torch.load('weights/weight97.pth', map_location='cpu')['model'])
model.requires_grad_(False)
model.eval()

if use_cuda:
    model = model.cuda()
if use_float16:
    model = model.half()

with torch.no_grad():
    features, regression, classification, anchors, seg = model(x)
    # print(ori_imgs)
    # ori_img = np.asarray(ori_imgs)
    # print(ori_img.size())
    # ratio = 640 / 1280
    # da_predict = seg[:, :, 0:(720 - 0), 0:(1280 - 0)]
    # print(seg.shape)

    # print(da_predict.shape)
    da_seg_mask = torch.nn.functional.interpolate(seg, size = [720,1280], mode='bilinear')
    # print(da_seg_mask.shape)

    _, da_seg_mask = torch.max(da_seg_mask, 1)

    # seg = torch.rand((1, 384, 640))
    # da_seg_mask = Activation('sigmoid')(da_seg_mask)
    # print(da_seg_mask.shape)
    color_mask_ls = []
    for i in range(da_seg_mask.size(0)):
    #   print(i)
      da_seg_mask_ = da_seg_mask[i].squeeze().cpu().numpy().round()
      # da_seg_mask = torch.argmax(da_seg_mask, dim = 0)
      # da_seg_mask[da_seg_mask < 0.5] = 0
      # da_seg_mask[da_seg_mask >= 0.5] = 1

      color_area = np.zeros((da_seg_mask_.shape[0], da_seg_mask_.shape[1], 3), dtype=np.uint8)

      # for label, color in enumerate(palette):
      #     color_area[result[0] == label, :] = color

      color_area[da_seg_mask_ == 1] = [0, 255, 0]
      color_area[da_seg_mask_ == 2] = [0, 0, 255]

      color_seg = color_area[..., ::-1]
    #   print(color_seg.shape)

      cv2.imwrite('seg_only_{}.jpg'.format(i),color_seg)


      # convert to BGR
      # color_seg = color_seg[..., ::-1]
      # # print(color_seg.shape)
      color_mask = np.mean(color_seg, 2)
      ori_img = ori_imgs[i]
    #   print(ori_img.shape)
      # ori_img = cv2.resize(ori_img, (1280, 768), interpolation=cv2.INTER_LINEAR)
      ori_img[color_mask != 0] = ori_img[color_mask != 0] * 0.5 + color_seg[color_mask != 0] * 0.5
      # img = img * 0.5 + color_seg * 0.5
      ori_img = ori_img.astype(np.uint8)
      # img = cv2.resize(ori_img, (1280, 720), interpolation=cv2.INTER_LINEAR)
      cv2.imwrite('seg_{}.jpg'.format(i), ori_img)
      # cv2.waitKey(0)
      color_mask_ls.append(color_mask)

    regressBoxes = BBoxTransform()
    clipBoxes = ClipBoxes()

    # print(x.shape)

    out = postprocess(x,
                      anchors, regression, classification,
                      regressBoxes, clipBoxes,
                      threshold, iou_threshold)


def display(preds, imgs, imshow=True, imwrite=False):
    global color_seg
    global color_mask

    for i in range(len(imgs)):
        if len(preds[i]['rois']) == 0:
            continue

        imgs[i] = imgs[i].copy()

        for j in range(len(preds[i]['rois'])):
            x1, y1, x2, y2 = preds[i]['rois'][j].astype(np.int)
            obj = obj_list[preds[i]['class_ids'][j]]
            score = float(preds[i]['scores'][j])
            plot_one_box(imgs[i], [x1, y1, x2, y2], label=obj,score=score,color=color_list[get_index_label(obj, obj_list)])

        # imgs[i] = cv2.resize(imgs[i], (1280, 768), interpolation=cv2.INTER_LINEAR)
        imgs[i][color_mask_ls[i] != 0] = imgs[i][color_mask_ls[i] != 0] * 0.5 + color_seg[color_mask_ls[i] != 0] * 0.5
        # imgs[i] = cv2.resize(imgs[i], (1280, 720), interpolation=cv2.INTER_LINEAR)

        if imshow:
            cv2.imshow('img', imgs[i])
            cv2.waitKey(0)

        if imwrite:
            # print('inside')
            cv2.imwrite(f'test/{i}.jpg', imgs[i])


out = invert_affine(framed_metas, out)
display(out, ori_imgs, imshow=False, imwrite=True)

print('running speed test...')
with torch.no_grad():
    print('test1: model inferring and postprocessing')
    print('inferring image for 10 times...')
    t1 = time.time()
    for _ in range(10):
        _, regression, classification, anchors, segmentation = model(x)


        out = postprocess(x,
                          anchors, regression, classification,
                          regressBoxes, clipBoxes,
                          threshold, iou_threshold)
        out = invert_affine(framed_metas, out)

    t2 = time.time()
    tact_time = (t2 - t1) / 10
    print(f'{tact_time} seconds, {1 / tact_time} FPS, @batch_size 1')

    # uncomment this if you want a extreme fps test
    print('test2: model inferring only')
    print('inferring images for batch_size 32 for 10 times...')
    t1 = time.time()
    x = torch.cat([x] * 32, 0)
    for _ in range(10):
        _, regression, classification, anchors, segmentation = model(x)
    
    t2 = time.time()
    tact_time = (t2 - t1) / 10
    print(f'{tact_time} seconds, {32 / tact_time} FPS, @batch_size 32')