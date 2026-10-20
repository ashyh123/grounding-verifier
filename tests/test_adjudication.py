"""Bilingual note entry saves only human notes, with exact English references."""
import hashlib
import json
import re

from fastapi.testclient import TestClient

from annotation.adjudication import make_app


def test_bilingual_note_flow_preserves_source_first_judgment_and_append_history(tmp_path):
    claim_id = 'ragtruth-9775-c19'
    passage = '{"city": "Santa Barbara"}'
    case = {'id': 'ragtruth-9775', 'generated_answer': 'A local business.',
            'context_passages': [passage], 'claims': [{
                'claim_id': claim_id, 'claim_text': 'A local business.',
                'upstream_verdict': 'UNSUPPORTED', 'overlapping_source_labels': [
                    {'text': 'PRIVATE_UPSTREAM_MARKER', 'label_type': 'Subtle Baseless Info'}]}]}
    drafts = tmp_path / 'drafts.jsonl'
    drafts.write_text(json.dumps(case) + '\n')
    original = drafts.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    zh = tmp_path / 'zh.json'
    translation = {'context_sha256': hashlib.sha256(json.dumps([passage], ensure_ascii=False).encode()).hexdigest(),
                   'claim_text': 'A local business.', 'answer_sha256': hashlib.sha256(case['generated_answer'].encode()).hexdigest(),
                   'claim_zh': '一家本地商家。', 'passages_zh': ['城市：圣巴巴拉。'],
                   'passage_titles': ['商家信息'], 'answer_zh': '一家本地商家。',
                   'upstream_note_zh': 'PRIVATE_TRANSLATED_UPSTREAM_MARKER'}
    zh.write_text(json.dumps({case['id']: translation}))
    notes = tmp_path / 'notes.jsonl'
    client = TestClient(make_app(drafts, zh, notes))
    url = f'/adjudicate/{claim_id}'
    page = client.get(url).text
    assert '一家本地商家。' in page and 'PRIVATE_UPSTREAM_MARKER' not in page
    assert 'PRIVATE_TRANSLATED_UPSTREAM_MARKER' not in page and not notes.exists()
    token = re.search(r'<script nonce="([^"]+)"', page).group(1)
    headers = {'X-Form-Token': token}
    endpoint = f'/api/notes/{claim_id}'
    final = {'stage': 'revision_notes', 'source_sha256': digest, 'action': 'keep',
             'items': [{'text_zh': '地点位于圣巴巴拉。', 'verdict': 'SUPPORTED',
                        'reason_zh': '看城市字段。', 'evidence': [{'index': 0, 'start': 1, 'end': len(passage)-1,
                                                              'quote': passage[1:-1]}]}]}
    assert client.post(endpoint, json=final, headers=headers).status_code == 409
    first = {'stage': 'first_judgment', 'source_sha256': digest, 'first_judgment': 'UNCERTAIN'}
    assert client.post(endpoint, json=first).status_code == 403
    response = client.post(endpoint, json=first, headers=headers)
    assert response.status_code == 200 and response.json()['upstream']['labels'][0]['text'] == 'PRIVATE_UPSTREAM_MARKER'
    assert 'PRIVATE_UPSTREAM_MARKER' in client.get(url).text
    # The first record remains immutable even if a later request chooses another verdict.
    assert client.post(endpoint, json={**first, 'first_judgment': 'SUPPORTED'}, headers=headers).json()['first_judgment'] == 'UNCERTAIN'
    assert client.post(endpoint, json=final, headers=headers).status_code == 200
    final['upstream_note_zh'] = '补充说明，等待英文修订。'
    assert client.post(endpoint, json=final, headers=headers).status_code == 200
    records = [json.loads(line) for line in notes.read_text().splitlines()]
    assert len(records) == 3 and records[0]['stage'] == 'first_judgment'
    assert all(r['scope'] == 'human_notes_only_not_gold' and r['first_judgment'] == 'UNCERTAIN' for r in records)
    assert records[-1]['status'] == 'pending_english_revision'
    assert '补充说明，等待英文修订。' in client.get(url).text
    before_invalid = notes.read_bytes()
    final['items'][0]['evidence'][0]['quote'] = '圣巴巴拉'
    assert client.post(endpoint, json=final, headers=headers).status_code == 422
    final['source_sha256'] = '0' * 64
    assert client.post(endpoint, json=final, headers=headers).status_code == 409
    assert notes.read_bytes() == before_invalid and drafts.read_bytes() == original
    assert not (tmp_path / 'decisions_round1.jsonl').exists()
    translation['context_sha256'] = '0' * 64
    zh.write_text(json.dumps({case['id']: translation}))
    assert client.get(url).status_code == 409


def test_pilot_review_feedback_is_per_claim_append_only_and_never_materializes_gold(tmp_path):
    drafts = tmp_path / 'drafts.jsonl'
    case = {'id': 'case-1', 'source': {'task_type': 'QA'}, 'context_passages': ['The count is 12.'],
            'generated_answer': 'The count is 12.', 'source_labels': [], 'claims': []}
    drafts.write_text(json.dumps(case) + '\n')
    original = drafts.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    reviews = tmp_path / 'reviews.jsonl'
    review = {'review_id': 'review-1', 'case_id': 'case-1', 'claim_id': 'claim-1',
              'source_sha256': digest, 'claim_text': 'The count is 12.', 'claim_zh': '数量是 12。',
              'suggested_verdict': 'SUPPORTED', 'reason_zh': '数字一致。', 'issues': [],
              'proposed_children': [], 'evidence_candidates': [], 'related_context': []}
    reviews.write_text(json.dumps(review) + '\n')
    decisions = tmp_path / 'decisions_round1.jsonl'
    confirmed = {'claim_id': 'already-confirmed', 'case_id': 'case-1', 'author': 'user',
                 'label_source': 'human_adjudicated', 'source_sha256': digest, 'verdict': 'UNSUPPORTED',
                 'claim_text': 'A prior decision.', 'note': '已由用户确认。'}
    decisions.write_text(json.dumps(confirmed) + '\n')
    original_decisions = decisions.read_bytes()
    feedback, notes = tmp_path / 'feedback.jsonl', tmp_path / 'notes.jsonl'
    client = TestClient(make_app(drafts, tmp_path / 'unused-translations.json', notes,
                                 reviews, feedback, decisions))
    page = client.get('/reviewed-pilot')
    assert page.status_code == 200
    assert 'already-confirmed' in page.text and '数量是 12。' in page.text
    token = re.search(r'<script nonce="([^"]+)"', page.text).group(1)
    headers = {'X-Form-Token': token}
    endpoint = '/api/pilot-review-feedback'
    body = {'review_id': 'review-1', 'source_sha256': digest, 'outcome': 'agree'}
    assert client.post(endpoint, json=body).status_code == 403
    assert client.post(endpoint, json={**body, 'outcome': 'change'}, headers=headers).status_code == 422
    assert client.post(endpoint, json={**body, 'source_sha256': 'stale'}, headers=headers).status_code == 409
    assert client.post(endpoint, json={**body, 'review_id': 'unknown'}, headers=headers).status_code == 409
    assert not feedback.exists()
    assert client.post(endpoint, json=body, headers=headers).status_code == 200
    first = feedback.read_bytes()
    assert client.post(endpoint, json={**body, 'outcome': 'change', 'comment_zh': '这条需要拆分。'},
                       headers=headers).status_code == 200
    assert feedback.read_bytes().startswith(first)
    records = [json.loads(line) for line in feedback.read_text().splitlines()]
    assert len(records) == 2 and records[0]['outcome'] == 'agree' and records[1]['outcome'] == 'change'
    assert all(r['scope'] == 'human_review_feedback_not_materialized_gold' and
               r['first_judgment'] is None for r in records)
    assert '这条需要拆分。' in client.get('/reviewed-pilot').text
    assert decisions.read_bytes() == original_decisions and drafts.read_bytes() == original
    assert not notes.exists()
    drafts.write_bytes(original + b'\n')
    before_stale = feedback.read_bytes()
    assert client.get('/reviewed-pilot').status_code == 409
    assert client.post(endpoint, json=body, headers=headers).status_code == 409
    assert feedback.read_bytes() == before_stale
