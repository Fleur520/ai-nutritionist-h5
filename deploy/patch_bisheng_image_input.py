"""Prepare an opt-in BiSheng 1.3.1 image-input patch, preserving its source.

The food workflow uploads photographs for a vision model, not document search.
Upstream still OCRs and indexes images when file_content_size is zero. This
patch adds an explicit skip_image_text_extraction flag; all other fields keep
the original parser. Output is a new file for an independently tested image or
read-only container mount. This command never edits the installed source.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


ANCHOR = '''        for one_file_url in value:
            file_name, file_path, texts, metadatas = self.get_upload_file_path_content(one_file_url)
'''
REPLACEMENT = '''        for one_file_url in value:
            # food-image-input-v1: explicit opt-in, never parse/index meal OCR.
            image_only = (key_info.get('skip_image_text_extraction') is True
                          and key_info.get('file_type') == 'image'
                          and file_content_max_size == 0)
            if image_only:
                from PIL import Image
                downloaded_path, file_name = file_download(one_file_url)
                file_name = KnowledgeService.get_upload_file_original_name(file_name)
                extension = file_name.rsplit('.', 1)[-1].lower()
                if extension not in self._image_ext:
                    raise ValueError('Image-only input requires a supported image')
                with Image.open(downloaded_path) as image:
                    if image.width * image.height > 16000000:
                        raise ValueError('Image-only input exceeds 16 million pixels')
                    image.verify()
                file_path = os.path.join(tempfile.gettempdir(), f'{md5_hash(one_file_url)}.{extension}')
                if os.path.abspath(downloaded_path) != os.path.abspath(file_path):
                    shutil.copyfile(downloaded_path, file_path)
                texts, metadatas = [], []
                all_metadata.append({'source': file_name, 'file_id': file_id,
                                     'knowledge_id': self.workflow_id})
            else:
                file_name, file_path, texts, metadatas = self.get_upload_file_path_content(one_file_url)
'''


def patch_source(source):
    source = source.replace('\r\n', '\n')
    if 'food-image-input-v1' in source:
        raise ValueError('Image-input patch is already present; do not apply twice')
    if source.count(ANCHOR) != 1:
        raise ValueError('Installed InputNode differs from the expected v1.3.1 structure')
    patched = source.replace(ANCHOR, REPLACEMENT)
    ast.parse(patched)
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve() or args.output.exists():
        raise ValueError('Output must be a new file distinct from the installed source')
    source = args.source.read_bytes()
    result = patch_source(source.decode('utf-8')).encode('utf-8')
    with args.output.open('xb') as output:
        output.write(result)
    print(json.dumps({'source_sha256': hashlib.sha256(source).hexdigest(),
                      'patched_sha256': hashlib.sha256(result).hexdigest(),
                      'output': str(args.output), 'feature_flag': 'skip_image_text_extraction'}))


if __name__ == '__main__':
    main()
