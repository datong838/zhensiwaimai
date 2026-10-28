import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import roster_post_lease as subject


class RosterLeaseBindingTests(unittest.TestCase):
    def test_actual_four_post_names_and_groups_match_same_original_mutex(self):
        posts = json.loads(Path(subject.__file__).with_name('posts.json').read_text())['posts']
        for name, post in posts.items():
            if post.get('port') not in (9230, 9231, 9232, 9233):
                continue
            port = post['port']
            physical = '/tmp/zhensi-jinsha-cua-exam.lock' if port == 9232 else f'/tmp/zhensi-post-{port}.lock'
            self.assertEqual(subject.registered_group(name, physical), post['mutexGroup'])
            self.assertEqual(subject.registered_group(post['mutexGroup'], physical), post['mutexGroup'])

    def test_wrong_or_unknown_binding_never_checks_or_acquires_a_lock(self):
        for group, lock in [('taobao-brand', '/tmp/zhensi-post-9231.lock'),
                            ('unknown', '/tmp/zhensi-post-9230.lock'),
                            ('../taobao-brand', '/tmp/zhensi-post-9230.lock')]:
            with patch.object(subject, 'assert_no_live_owner') as owner, patch.object(subject.run_all, 'acquire_post_group_lock') as acquire:
                with self.assertRaises(ValueError):
                    with subject.original_post_lease(group, 'fixture', lock):
                        self.fail('invalid binding entered')
                owner.assert_not_called()
                acquire.assert_not_called()

    def test_ambiguous_or_malformed_registry_rejects(self):
        cases = [({'a': {'port': 9230, 'mutexGroup': 'same'}, 'b': {'port': 9230, 'mutexGroup': 'same'}}, 'same'),
                 ({'a': {'port': True, 'mutexGroup': 'valid'}}, 'a'),
                 ({'a': {'port': 9230, 'mutexGroup': '../escape'}}, 'a')]
        for posts, group in cases:
            with patch.object(Path, 'read_text', return_value=json.dumps({'posts': posts})):
                with self.assertRaises(ValueError):
                    subject.registered_group(group, '/tmp/zhensi-post-9230.lock')

    def test_alias_uses_canonical_existing_lock_and_releases_same_handle_on_error(self):
        handle = object()
        with patch.object(subject, 'assert_no_live_owner') as owner, patch.object(subject.run_all, 'acquire_post_group_lock', return_value=handle) as acquire, patch.object(subject.run_all, 'release_post_group_lock') as release:
            with self.assertRaisesRegex(RuntimeError, 'fixture-operation-failed'):
                with subject.original_post_lease('taobao-brand', 'fixture', '/tmp/zhensi-post-9230.lock'):
                    raise RuntimeError('fixture-operation-failed')
            acquire.assert_called_once_with('taobao-brand-9230', 'fixture')
            self.assertEqual(owner.call_args_list[0].args[0], subject.run_all.POST_GROUP_LOCK_DIR / 'taobao-brand-9230.lock')
            release.assert_called_once_with(handle)

    def test_busy_original_group_never_releases_another_handle(self):
        with patch.object(subject, 'assert_no_live_owner'), patch.object(subject.run_all, 'acquire_post_group_lock', return_value=None), patch.object(subject.run_all, 'release_post_group_lock') as release:
            with self.assertRaisesRegex(ValueError, 'post-lease-busy'):
                with subject.original_post_lease('taobao-brand', 'fixture', '/tmp/zhensi-post-9230.lock'):
                    self.fail('busy entered')
            release.assert_not_called()

    def test_success_releases_original_handle(self):
        handle = object()
        with patch.object(subject, 'assert_no_live_owner'), patch.object(subject.run_all, 'acquire_post_group_lock', return_value=handle) as acquire, patch.object(subject.run_all, 'release_post_group_lock') as release:
            with subject.original_post_lease('meituan-9233', 'fixture', '/tmp/zhensi-post-9233.lock'):
                release.assert_not_called()
            acquire.assert_called_once_with('meituan-9233', 'fixture')
            release.assert_called_once_with(handle)

    def test_live_owner_does_not_acquire_or_release(self):
        with patch.object(subject, 'assert_no_live_owner', side_effect=ValueError('post-live-owner-busy')), patch.object(subject.run_all, 'acquire_post_group_lock') as acquire, patch.object(subject.run_all, 'release_post_group_lock') as release:
            with self.assertRaisesRegex(ValueError, 'post-live-owner-busy'):
                with subject.original_post_lease('taobao-brand', 'fixture', '/tmp/zhensi-post-9230.lock'):
                    self.fail('owner busy entered')
            acquire.assert_not_called()
            release.assert_not_called()


if __name__ == '__main__':
    unittest.main()
