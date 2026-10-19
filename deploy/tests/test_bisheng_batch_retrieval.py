import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bisheng_food_fastpath import enable_image_reference
from bisheng_food_workflow import build_workflow
from test_bisheng_food_workflow import answer, code_main, document, native_retriever


class BatchedDocumentRetrievalTests(unittest.TestCase):
    def store(self, *, vectors=None, partition=7, provider='OpenAIEmbeddings', metadata=None):
        self.embeddings, self.searches, self.authorizations = [], [], []
        def embed(texts):
            self.embeddings.append(texts)
            return [[3., 4.] for unused in texts] if vectors is None else vectors
        def search(**kwargs):
            self.searches.append(kwargs)
            result = []
            for query in self.embeddings[-1]:
                doc = document(answer(code=query, name=query), **(metadata or {}))
                entity = dict(doc.metadata, text=doc.page_content)
                result.append([SimpleNamespace(entity=entity, score=.2)])
            return result
        embedding = SimpleNamespace(embeddings=type(provider, (), {})(), embed_documents=embed)
        store = SimpleNamespace(col=[SimpleNamespace(search=search)], collection_embeddings=[embedding],
                                col_partition_key=[partition], fields=['text', 'vector', 'knowledge_id', 'file_id', 'chunk_index', 'source', 'extra'],
                                _vector_field='vector', _text_field='text', _partition_field='knowledge_id', search_params={'metric_type': 'L2'})
        return store

    def test_one_batch_preserves_query_order_deduplicates_and_keeps_authorized_partition(self):
        store = self.store()
        retrieve = native_retriever(store, self.authorizations)
        rows = retrieve([{'name': 'rice'}, {'name': 'yogurt'}, {'name': 'rice'}], 7, .1, 8, True)['documents']
        self.assertEqual(self.embeddings, [['rice', 'yogurt']])
        self.assertEqual(len(self.searches), 1)
        request = self.searches[0]
        self.assertEqual(request['data'], [[.6, .8], [.6, .8]])
        self.assertEqual(request['expr'], 'knowledge_id=="7"')
        self.assertEqual(request['timeout'], 8)
        self.assertNotIn('vector', request['output_fields'])
        self.assertEqual([json.loads(row[0]['raw_record'])['record']['code'] for row in rows], ['rice', 'yogurt', 'rice'])
        self.assertTrue(self.authorizations[0]['params']['_is_check_auth'])
        self.assertEqual(self.authorizations[0]['params']['collection_name'][0]['key'], 7)

    def test_wrong_partition_or_embedding_type_fails_before_model_or_search(self):
        for options in ({'partition': 8}, {'provider': 'OllamaEmbeddings'}):
            store = self.store(**options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                native_retriever(store, [])([{'name': 'rice'}], 7, .1, 8, True)
            self.assertFalse(self.embeddings)
            self.assertFalse(self.searches)

    def test_invalid_vectors_are_rejected_before_milvus(self):
        for vectors in ([], [[]], [[0, 0]], [[float('nan'), 1]], [[True, 1]], [[1, 2], [1, 2]]):
            store = self.store(vectors=vectors)
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                native_retriever(store, [])([{'name': 'rice'}], 7, .1, 8, True)
            self.assertFalse(self.searches)

    def test_batch_results_cannot_cross_knowledge_boundary(self):
        store = self.store(metadata={'knowledge_id': '8'})
        with self.assertRaises(ValueError):
            native_retriever(store, [])([{'name': 'rice'}], 7, .1, 8, True)

    def test_batch_results_still_require_original_document_hash(self):
        store = self.store(metadata={'extra': '{}'})
        with self.assertRaises(ValueError):
            native_retriever(store, [])([{'name': 'rice'}], 7, .1, 8, True)

    def test_batch_response_count_must_match_embedding_count(self):
        store = self.store()
        store.col[0].search = lambda **kwargs: []
        with self.assertRaises(ValueError):
            native_retriever(store, [])([{'name': 'rice'}], 7, .1, 8, True)

    def test_workflow_connects_batch_stage_timings_without_changing_food_schema(self):
        body = enable_image_reference(build_workflow(7, 11, 12, snapshot_id='a' * 64, batch_document_search=True), 'http://storage:9000')
        nodes = {node['id']: node for node in body['data']['nodes']}
        get = lambda key: {p['key']: p['value'] for g in nodes[key]['data']['group_params'] for p in g['params']}
        self.assertIn({'key': 'batch_search', 'type': 'input', 'value': True}, get('code_retrieve')['code_input'])
        finish = code_main(get('code_result')['code'])
        result = json.loads(finish(json.dumps({'schema_version': 1, 'snapshot_id': 'a' * 64, 'items': []}),
                                   0, 1, 2, 3, 4, 5, json.dumps({'retrieval_embedding': 6}))['result'])
        self.assertEqual(result['items'], [])
        self.assertEqual(result['timings_ms']['retrieval_embedding'], 6)
