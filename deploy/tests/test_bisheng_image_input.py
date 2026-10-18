"""Contract checks for the opt-in image branch and unchanged document parsing."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from patch_bisheng_image_input import patch_source
from bisheng_food_workflow import build_workflow

# Minimal old InputNode contract: the exact upstream loop is intentionally
# retained, including the OCR call before the zero-text-length check.
SOURCE = '''class InputNode:
    def parse_upload_file(self, key, key_info, value):
        all_metadata = []
        all_file_content = ''
        original_file_path = []
        image_files_path = []
        file_id = 'fixture-file'
        file_content_max_size = int(key_info.get('file_content_size', 15000))
        for one_file_url in value:
            file_name, file_path, texts, metadatas = self.get_upload_file_path_content(one_file_url)
            original_file_path.append(file_path)
            if file_name.split('.')[-1].lower() in self._image_ext:
                image_files_path.append(file_path)
            if file_content_max_size:
                all_file_content += '\\n'.join(texts)[:file_content_max_size]
            if not texts:
                continue
            self.index_texts(texts)
            all_metadata.append(metadatas[0])
        return {'metadata':all_metadata,'text':all_file_content,
                'paths':original_file_path,'images':image_files_path}
'''


class ImageInputTests(unittest.TestCase):
    def node(self, folder, filename='meal.jpg'):
        path = Path(folder) / filename
        Image.new('RGB',(80,40),'green').save(path,format='JPEG')
        scope={'os':os,'shutil':shutil,'tempfile':SimpleNamespace(gettempdir=lambda:folder),
               'file_download':lambda url:(str(path),filename),
               'KnowledgeService':SimpleNamespace(get_upload_file_original_name=lambda name:name),
               'md5_hash':lambda value:hashlib.md5(value.encode()).hexdigest()}
        exec(patch_source(SOURCE),scope)
        node=scope['InputNode']()
        node._image_ext=['jpg','jpeg','png','bmp']
        node.workflow_id='test-food-flow'
        node.get_upload_file_path_content=Mock(return_value=(filename,str(path),['OCR text'],[{'source':filename}]))
        node.index_texts=Mock()
        return node,path

    def test_opt_in_keeps_visual_file_without_ocr_or_vector_write(self):
        with tempfile.TemporaryDirectory() as folder:
            node,path=self.node(folder)
            result=node.parse_upload_file('meal',{'file_type':'image','file_content_size':0,
                                                 'skip_image_text_extraction':True},['http://fixture/meal'])
            node.get_upload_file_path_content.assert_not_called()
            node.index_texts.assert_not_called()
            self.assertEqual(result['text'],'')
            self.assertEqual(len(result['images']),1)
            self.assertEqual(Path(result['images'][0]).read_bytes(),path.read_bytes())
            self.assertEqual(result['metadata'][0]['source'],'meal.jpg')

    def test_missing_flag_non_image_and_nonzero_text_keep_original_parser(self):
        cases=[{'file_type':'image','file_content_size':0},
               {'file_type':'file','file_content_size':0,'skip_image_text_extraction':True},
               {'file_type':'image','file_content_size':500,'skip_image_text_extraction':True},
               {'file_type':'image','file_content_size':0,'skip_image_text_extraction':'true'}]
        for config in cases:
            with self.subTest(config=config), tempfile.TemporaryDirectory() as folder:
                node,_=self.node(folder)
                node.parse_upload_file('meal',config,['http://fixture/meal'])
                node.get_upload_file_path_content.assert_called_once()
                node.index_texts.assert_called_once()

    def test_invalid_image_is_not_passed_to_model(self):
        with tempfile.TemporaryDirectory() as folder:
            node,path=self.node(folder)
            path.write_bytes(b'not an image')
            with self.assertRaises(Exception):
                node.parse_upload_file('meal',{'file_type':'image','file_content_size':0,
                                              'skip_image_text_extraction':True},['http://fixture/meal'])
            node.index_texts.assert_not_called()

    def test_different_platform_source_and_double_patch_fail_closed(self):
        with self.assertRaises(ValueError):patch_source('class InputNode: pass')
        with self.assertRaises(ValueError):patch_source(patch_source(SOURCE))

    def test_generated_flag_is_explicit_and_keeps_native_upload(self):
        graph=build_workflow(202,44,44,snapshot_id='a'*64,image_only_input=True)['data']
        node=next(n for n in graph['nodes'] if n['id']=='input_meal')
        field=node['data']['group_params'][0]['params'][0]['value'][0]
        self.assertEqual(field['type'],'file')
        self.assertEqual(field['file_type'],'image')
        self.assertEqual(field['file_content_size'],0)
        self.assertIs(field['skip_image_text_extraction'],True)


if __name__ == '__main__':unittest.main()
