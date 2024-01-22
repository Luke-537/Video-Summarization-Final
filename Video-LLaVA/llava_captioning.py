import os
os.environ['CUDA_VISIBLE_DEVICES'] = '0'
import sys
sys.path.append('/home/reutemann/Dino-Video-Summarization-Transformer')
import torch
sys.path.append('/home/reutemann/Dino-Video-Summarization-Transformer/Video-LLaVA')
import csv

from llava.constants import X_TOKEN_INDEX, DEFAULT_X_TOKEN
from llava.conversation import conv_templates, SeparatorStyle
from llava.model.builder import load_pretrained_model
from llava.utils import disable_torch_init
from llava.mm_utils import tokenizer_X_token, get_model_name_from_path, KeywordsStoppingCriteria
from utils.parser import parse_args, load_config
from datasets_custom import FrameSelectionLoader


def main():
    """
    Generating Captions for uniformly or adaptively sampled videos from MSVD using Video-LLaVA.
    """

    # loading the model, device tokenizer and image processor
    disable_torch_init()
    inp = 'Give me a single-sentence caption for this video.'
    model_path = 'LanguageBind/Video-LLaVA-7B'
    device = 'cuda'
    load_4bit, load_8bit = True, False
    model_name = get_model_name_from_path(model_path)
    tokenizer, model, processor, context_len = load_pretrained_model(model_path, None, model_name, load_8bit, load_4bit, device=device)
    image_processor = processor['image']
    conv_mode = "llava_v1"
    conv = conv_templates[conv_mode].copy()
    roles = conv.roles
    
    # setting the dataset arguments
    args = parse_args()
    args.cfg_file = "/home/reutemann/Dino-Video-Summarization-Transformer/models/configs/Kinetics/TimeSformer_divST_8x32_224.yaml"
    config = load_config(args)
    config.DATA.PATH_TO_DATA_DIR = "/home/reutemann/Dino-Video-Summarization-Transformer/MSVD"
    config.DATA.PATH_PREFIX = "/graphics/scratch/datasets/MSVD/YouTubeClips"
    config.DATASET = "MSVD"
    config.LOSS_FILE = "/home/reutemann/Dino-Video-Summarization-Transformer/loss_values/loss_msvd_4_3_30.json"

    # creating the dataset that returns the selected frames as tensors
    dataset = FrameSelectionLoader(
        cfg=config,
        pre_sampling_rate=4,
        selection_method="adaptive",
        num_frames=8,
        augmentations=False
    )
    print(f"Loaded dataset of length: {len(dataset)}")

    # path to the output CSV
    export_file = "/home/reutemann/Dino-Video-Summarization-Transformer/eval_logs/captions_adaptive.csv"

    # tokenizing the input videos
    key = ['video']
    print(f"{roles[1]}: {inp}")
    inp = DEFAULT_X_TOKEN['VIDEO'] + '\n' + inp
    conv.append_message(conv.roles[0], inp)
    conv.append_message(conv.roles[1], None)
    prompt = conv.get_prompt()
    input_ids = tokenizer_X_token(prompt, tokenizer, X_TOKEN_INDEX['VIDEO'], return_tensors='pt').unsqueeze(0).cuda()
    stop_str = conv.sep if conv.sep_style != SeparatorStyle.TWO else conv.sep2
    keywords = [stop_str]
    stopping_criteria = KeywordsStoppingCriteria(keywords, tokenizer, input_ids)

    # iterating over the dataset
    for i in range(len(dataset)):
        video_tensor = torch.empty(1, 8, 3, 224, 224)

        # augmenting every frame of the video with the Video-LLaVA image tower
        for j in range(8):
            # C T H W -> T C H W and C H W -> H W C
            image = dataset[i][0].permute(1, 0, 2, 3)[j].permute(1, 2, 0).numpy()
            video_tensor[0][j] = image_processor(image, return_tensor='pt')['pixel_values'].squeeze(0)

        # P C T H W -> P T C H W
        video_tensor = video_tensor.permute(0, 2, 1, 3, 4)
        if type(video_tensor) is list:
            tensor = [video.to(model.device, dtype=torch.float16) for video in video_tensor]
        else:
            tensor = video_tensor.to(model.device, dtype=torch.float16)

        # run inference on the model
        with torch.inference_mode():
            output_ids = model.generate(
                input_ids,
                images=[tensor, key],
                do_sample=True,
                temperature=0.1,
                max_new_tokens=1024,
                use_cache=True,
                stopping_criteria=[stopping_criteria])

        # decode and print the output tensor
        outputs = tokenizer.decode(output_ids[0, input_ids.shape[1]:]).strip()
        print(outputs)
        print(str(i) + "/" + str(len(dataset)))

        #write outputs in csv file
        with open(export_file, 'a', newline='') as file:
            # Create a CSV writer object
            writer = csv.writer(file, delimiter=' ')
            writer.writerow([dataset[i][2], outputs])


if __name__ == '__main__':
    main()
