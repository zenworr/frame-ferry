"""Run one group of the discovered Python tests."""

import argparse
import unittest


def test_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_cases(item)
        else:
            yield item


def suite_group(test):
    method = getattr(test, test.id().rsplit('.', 1)[-1])
    return getattr(method, 'suite_group', getattr(test, 'suite_group', 'headless'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=('headless', 'player', 'slow', 'ui'))
    group = parser.parse_args().group
    loader = unittest.TestLoader()
    discovered = loader.discover('tests', top_level_dir='.')
    if loader.errors:
        parser.exit(1, '\n'.join(loader.errors))
    selected = unittest.TestSuite(test for test in test_cases(discovered) if suite_group(test) == group)
    if not selected.countTestCases():
        parser.exit(1, f'No tests in the {group} group.\n')
    return not unittest.TextTestRunner(verbosity=2).run(selected).wasSuccessful()


if __name__ == '__main__':
    raise SystemExit(main())
