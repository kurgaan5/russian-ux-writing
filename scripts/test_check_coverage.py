"""Regression tests for coverage bookkeeping, not an evaluation of model copywriting."""
import unittest

import check_coverage as cc


class CoverageTests(unittest.TestCase):
    def setUp(self):
        full = cc.read(cc.REGISTRY)
        wanted = {'CTX-01', 'LNG-04', 'FIT-02', 'DAT-04'}
        self.registry = {'checks': [c for c in full['checks'] if c['id'] in wanted]}
        self.inventory = {
            'mode': 'review',
            'materials': [{'id': 'M1', 'locator': 'synthetic test brief', 'status': 'read',
                           'reason': 'All fixture input is supplied below', 'used_for': 'All fixture units'}],
            'units': [
                {'id': 'S', 'kind': 'scope', 'parent': None, 'tags': [], 'locator': 'fixture scope',
                 'text': 'Selection form only', 'context': 'Navigation is excluded'},
                {'id': 'B', 'kind': 'block', 'parent': 'S', 'tags': [], 'locator': 'fixture block',
                 'text': 'Date selection', 'context': 'Select date to continue'},
                {'id': 'T1', 'kind': 'text', 'parent': 'B', 'tags': [], 'locator': 'fixture hint',
                 'text': 'Выберите дату чтобы продолжить', 'candidate_text': 'Выберите дату, чтобы продолжить', 'context': 'Required date'},
                {'id': 'T2', 'kind': 'text', 'parent': 'B', 'tags': ['button'], 'locator': 'fixture button',
                 'text': 'Продолжить', 'context': 'Opens the next step'}]}
        self.ledger = cc.make_ledger(self.registry, self.inventory)
        self.ledger['material_review'] = 'Synthetic brief fully supplied; no external source used'
        self.ledger['inventory_review'] = 'Two text units and their block accounted for'
        self.ledger['editorial_decisions'] = [{
            'block_id': 'B', 'intent': 'Select a date and continue',
            'must_keep': ['Date is required; continuation opens next step'],
            'pattern_ids': ['EX-20'], 'transfer': 'Keep a direct instruction and its real action',
            'candidates': [{'id': 'v1', 'operation': 'Keep clear copy and restore punctuation',
                            'texts': {'T1': 'Выберите дату, чтобы продолжить', 'T2': 'Продолжить'},
                            'benefit': 'Correct purpose-clause punctuation', 'cost': 'No meaning change'}],
            'selected': 'v1', 'reason': 'The source already names the required input and purpose'}]
        # These strings exercise required bookkeeping fields; they are not model evaluation results.
        self.ledger['passes'] = {p: 'Fixture bookkeeping evidence for ' + p for p in cc.PASSES}
        self.ledger['second_look'] = {'B': 'Instruction and action have separate roles',
                                     'T2': 'A neutral next-step command is appropriate'}
        self.ledger['findings'] = [{'id': 'F1', 'type': 'fix', 'title': 'Missing comma',
                                   'check_ids': ['LNG-04'], 'unit_ids': ['T1'],
                                   'before': 'Выберите дату чтобы продолжить',
                                   'after': 'Выберите дату, чтобы продолжить',
                                   'why': 'Purpose clause requires a comma'}]
        for row in self.ledger['rows']:
            cid, uid = row['check_id'], row['unit_id']
            if uid is None:
                continue
            if cid == 'FIT-02':
                row.update(status='unverified', evidence='No render geometry supplied in fixture')
                self.ledger['limitations'].append({'check_id': cid, 'unit_id': uid,
                                                   'reason': 'Final text not rendered'})
            elif cid == 'LNG-04' and uid == 'T1':
                row.update(status='finding', evidence='Comma missing before purpose clause', finding_ids=['F1'])
            else:
                row.update(status='pass', evidence='Scope excludes navigation' if cid == 'CTX-01'
                           else 'One-word button needs no internal punctuation')

    def validate(self):
        return cc.validate(self.registry, self.inventory, self.ledger)

    def test_valid_review_distinguishes_unverified(self):
        result = self.validate()
        self.assertTrue(result['coverage_accounted_for'])
        self.assertFalse(result['all_applicable_verified'])
        self.assertFalse(result['semantic_quality_verified_by_script'])
        self.assertEqual(result['statuses']['unverified'], 2)

    def test_initialization_never_auto_passes(self):
        initial = cc.make_ledger(self.registry, self.inventory)
        self.assertEqual({r['status'] for r in initial['rows']}, {'pending', 'not_applicable'})

    def test_missing_pair_for_second_text_is_rejected(self):
        self.ledger['rows'] = [r for r in self.ledger['rows']
                               if (r['check_id'], r['unit_id']) != ('LNG-04', 'T2')]
        with self.assertRaisesRegex(ValueError, 'Coverage mismatch'):
            self.validate()

    def test_absent_format_cannot_pass(self):
        row = next(r for r in self.ledger['rows'] if r['unit_id'] is None)
        row['status'] = 'pass'
        with self.assertRaisesRegex(ValueError, 'absent component cannot pass'):
            self.validate()

    def test_required_grammar_cannot_be_skipped(self):
        row = next(r for r in self.ledger['rows'] if r['check_id'] == 'LNG-04' and r['unit_id'] == 'T2')
        row['status'] = 'not_applicable'
        with self.assertRaisesRegex(ValueError, 'required for this target'):
            self.validate()

    def test_pending_is_rejected(self):
        self.ledger['rows'][0]['status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'pending/invalid'):
            self.validate()

    def test_changed_source_invalidates_coverage(self):
        self.inventory['units'][2]['text'] += '!'
        with self.assertRaisesRegex(ValueError, 'Stale inventory'):
            self.validate()

    def test_changed_proposal_invalidates_coverage(self):
        self.inventory['units'][2]['candidate_text'] = 'Выберите дату'
        with self.assertRaisesRegex(ValueError, 'Stale inventory'):
            self.validate()

    def test_changed_registry_invalidates_coverage(self):
        self.registry['checks'][0]['criterion'] += ' Updated'
        with self.assertRaisesRegex(ValueError, 'Registry changed'):
            self.validate()

    def test_unlinked_finding_is_rejected(self):
        self.ledger['findings'][0]['unit_ids'].append('T2')
        with self.assertRaisesRegex(ValueError, 'unit links incomplete'):
            self.validate()

    def test_missing_second_look_is_rejected(self):
        self.ledger['second_look'].pop('T2')
        with self.assertRaisesRegex(ValueError, 'second look required'):
            self.validate()

    def test_unverified_needs_visible_limitation(self):
        self.ledger['limitations'].pop()
        with self.assertRaisesRegex(ValueError, 'visible limitation'):
            self.validate()

    def test_unfinished_source_blocks_completion(self):
        self.inventory['materials'][0]['status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'Unfinished material'):
            self.validate()

    def test_missing_material_summary_blocks_completion(self):
        self.ledger['material_review'] = ''
        with self.assertRaisesRegex(ValueError, 'material collection'):
            self.validate()

    def test_repeated_units_need_all_locations(self):
        self.inventory['units'][3]['count'] = 3
        self.inventory['units'][3]['locations'] = ['button 1', 'button 2']
        with self.assertRaisesRegex(ValueError, 'repeated locations'):
            self.validate()

    def test_write_rejects_unfixed_draft(self):
        self.inventory['mode'] = 'write'
        self.ledger['mode'] = 'write'
        self.ledger['inventory_sha256'] = cc.digest(self.inventory)
        with self.assertRaisesRegex(ValueError, 'selected candidate differs|fix known issues'):
            self.validate()

    def test_clarification_cannot_count_as_verified(self):
        self.ledger['findings'][0].update(type='clarify', question='Which action is implemented?')
        self.inventory['units'][2].pop('candidate_text')
        self.ledger['inventory_sha256'] = cc.digest(self.inventory)
        self.ledger['editorial_decisions'][0]['selected'] = 'original'
        with self.assertRaisesRegex(ValueError, 'clarification must remain unverified'):
            self.validate()

    def test_write_cannot_finish_with_blank_required_text(self):
        self.inventory['mode'] = 'write'
        self.inventory['units'][2]['text'] = ''
        with self.assertRaisesRegex(ValueError, 'writing mode needs final text'):
            self.validate()

    def test_write_accepts_checked_final_copy_with_honest_fit_limit(self):
        self.inventory['mode'] = 'write'
        self.inventory['units'][2]['text'] = 'Выберите дату, чтобы продолжить'
        self.ledger['mode'] = 'write'
        self.ledger['inventory_sha256'] = cc.digest(self.inventory)
        self.ledger['findings'] = []
        for r in self.ledger['rows']:
            if r['finding_ids']:
                r.update(status='pass', finding_ids=[], evidence='Comma restored before purpose clause')
        self.ledger['second_look']['T1'] = 'Instruction names date and purpose without an unsupported promise'
        self.assertEqual(self.validate()['findings'], 0)

    def test_registry_is_complete_and_generated_catalog_is_current(self):
        full = cc.read(cc.REGISTRY)
        checks = cc.registry_checks(full)
        self.assertEqual(len(checks), 127)
        self.assertEqual(len({c['group'] for c in checks}), 13)
        rendered = (cc.REGISTRY.parent / 'checks.md').read_text(encoding='utf-8')
        self.assertEqual(rendered, cc.render(full))

    def test_missing_editorial_decision_is_rejected(self):
        self.ledger['editorial_decisions'] = []
        with self.assertRaisesRegex(ValueError, 'every block with authored copy'):
            self.validate()

    def test_unreadable_example_reference_is_rejected(self):
        self.ledger['editorial_decisions'][0]['pattern_ids'] = ['EX-999']
        with self.assertRaisesRegex(ValueError, 'valid source example'):
            self.validate()

    def test_alternative_must_match_proposed_copy(self):
        self.ledger['editorial_decisions'][0]['candidates'][0]['texts']['T1'] = 'Другая строка'
        with self.assertRaisesRegex(ValueError, 'selected candidate differs'):
            self.validate()

    def test_partial_block_candidate_cannot_validate_the_whole_block(self):
        self.ledger['editorial_decisions'][0]['candidates'][0]['texts'].pop('T1')
        with self.assertRaisesRegex(ValueError, 'every authored text in the block'):
            self.validate()

    def test_complete_candidate_can_keep_a_clear_button_without_a_finding(self):
        self.assertNotIn('candidate_text', self.inventory['units'][3])
        self.assertEqual(self.validate()['findings'], 1)

    def test_candidate_does_not_require_rewriting_numeric_values(self):
        self.inventory['units'].append({
            'id': 'V', 'kind': 'text', 'parent': 'B', 'tags': ['data'],
            'content_role': 'value', 'value_reason': 'Selected calendar day',
            'locator': 'fixture date', 'text': '24', 'context': 'Visible day value'})
        units = cc.inventory_units(self.inventory)
        self.assertEqual(cc.validate_editorial(self.inventory, self.ledger, units), 1)

    def test_selected_change_cannot_disappear_from_report(self):
        self.ledger['findings'] = []
        with self.assertRaisesRegex(ValueError, 'selected change absent from findings'):
            self.validate()

    def test_values_keep_data_checks_without_prose_rewriting(self):
        full = cc.read(cc.REGISTRY)
        checks = [c for c in full['checks'] if c['id'] in ('CLR-13', 'DAT-06', 'TYP-03')]
        unit = {'id': 'V', 'kind': 'text', 'tags': ['data'], 'content_role': 'value', 'text': '14:00'}
        pairs = cc.expected_pairs(checks, [unit])
        self.assertIn(('CLR-13', None), pairs)
        self.assertIn(('DAT-06', 'V'), pairs)
        self.assertIn(('TYP-03', 'V'), pairs)

    def test_copy_role_is_safe_default(self):
        checks = [c for c in cc.read(cc.REGISTRY)['checks'] if c['id'] == 'CLR-13']
        pairs = cc.expected_pairs(checks, [{'id': 'T', 'kind': 'text', 'tags': []}])
        self.assertIn(('CLR-13', 'T'), pairs)

    def test_value_cannot_drop_data_checks(self):
        self.inventory['units'][3].update(content_role='value', value_reason='A numeric time value', text='14:00', tags=[])
        with self.assertRaisesRegex(ValueError, 'values must retain data checks'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
