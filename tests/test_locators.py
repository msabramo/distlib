# -*- coding: utf-8 -*-
#
# Copyright (C) 2012-2013 Vinay Sajip.
# Licensed to the Python Software Foundation under a contributor agreement.
# See LICENSE.txt and CONTRIBUTORS.txt.
#
from __future__ import unicode_literals
import os
import sys

from compat import unittest

from distlib.compat import url2pathname, urlparse, urljoin
from distlib.database import DistributionPath, make_graph, make_dist
from distlib.locators import (SimpleScrapingLocator, PyPIRPCLocator,
                              PyPIJSONLocator, DirectoryLocator,
                              DistPathLocator, AggregatingLocator,
                              JSONLocator, DistPathLocator,
                              DependencyFinder, locate,
                              get_all_distribution_names, default_locator)

HERE = os.path.abspath(os.path.dirname(__file__))

PYPI_RPC_HOST = 'http://python.org/pypi'

PYPI_WEB_HOST = os.environ.get('PYPI_WEB_HOST', 'https://pypi.python.org/simple/')

class LocatorTestCase(unittest.TestCase):

    @unittest.skipIf('SKIP_SLOW' in os.environ, 'Skipping slow test')
    def test_xmlrpc(self):
        locator = PyPIRPCLocator(PYPI_RPC_HOST)
        try:
            result = locator.get_project('sarge')
        except Exception:     # pragma: no cover
            raise unittest.SkipTest('PyPI XML-RPC not available')
        self.assertIn('0.1', result)
        dist = result['0.1']
        self.assertEqual(dist.name, 'sarge')
        self.assertEqual(dist.version, '0.1')
        self.assertEqual(dist.source_url,
                         'https://pypi.python.org/packages/source/s/sarge/'
                         'sarge-0.1.tar.gz')
        self.assertEqual(dist.digest,
                         ('md5', '961ddd9bc085fdd8b248c6dd96ceb1c8'))
        try:
            names = locator.get_distribution_names()
        except Exception:   # pragma: no cover
            raise unittest.SkipTest('PyPI XML-RPC not available')
        self.assertGreater(len(names), 25000)

    @unittest.skipIf('SKIP_SLOW' in os.environ, 'Skipping slow test')
    def test_json(self):
        locator = PyPIJSONLocator(PYPI_RPC_HOST)
        result = locator.get_project('sarge')
        self.assertIn('0.1.1', result)
        dist = result['0.1.1']
        self.assertEqual(dist.name, 'sarge')
        self.assertEqual(dist.version, '0.1.1')
        self.assertEqual(dist.source_url,
                         'https://pypi.python.org/packages/source/s/sarge/'
                         'sarge-0.1.1.tar.gz')
        self.assertEqual(dist.digest,
                         ('md5', '2a9b9d46e4ef6ae51e2a5ff7de93d9dd'))
        self.assertRaises(NotImplementedError, locator.get_distribution_names)

    @unittest.skipIf('SKIP_SLOW' in os.environ, 'Skipping slow test')
    def test_scraper(self):
        locator = SimpleScrapingLocator('https://pypi.python.org/simple/')
        for name in ('sarge', 'Sarge'):
            result = locator.get_project(name)
            self.assertIn('0.1', result)
            dist = result['0.1']
            self.assertEqual(dist.name, 'sarge')
            self.assertEqual(dist.version, '0.1')
            self.assertEqual(dist.source_url,
                             'https://pypi.python.org/packages/source/s/sarge/'
                             'sarge-0.1.tar.gz')
            self.assertEqual(dist.digest,
                             ('md5', '961ddd9bc085fdd8b248c6dd96ceb1c8'))
        return
        # The following is too slow
        names = locator.get_distribution_names()
        self.assertGreater(len(names), 25000)

    @unittest.skipIf('SKIP_SLOW' in os.environ, 'Skipping slow test')
    def test_unicode_project_name(self):
        # Just checking to see that no exceptions are raised.
        NAME = '\u2603'
        locator = SimpleScrapingLocator('https://pypi.python.org/simple/')
        result = locator.get_project(NAME)
        self.assertFalse(result)
        locator = PyPIJSONLocator('https://pypi.python.org/pypi/')
        result = locator.get_project(NAME)
        self.assertFalse(result)

    def test_dir(self):
        d = os.path.join(HERE, 'fake_archives')
        locator = DirectoryLocator(d)
        expected = os.path.join(HERE, 'fake_archives', 'subdir',
                                'subsubdir', 'Flask-0.9.tar.gz')
        def get_path(url):
            t = urlparse(url)
            return url2pathname(t.path)

        for name in ('flask', 'Flask'):
            result = locator.get_project(name)
            self.assertIn('0.9', result)
            dist = result['0.9']
            self.assertEqual(dist.name, 'Flask')
            self.assertEqual(dist.version, '0.9')
            self.assertEqual(os.path.normcase(get_path(dist.source_url)),
                             os.path.normcase(expected))
        names = locator.get_distribution_names()
        expected = set(['Flask', 'python-gnupg', 'coverage', 'Django'])
        if sys.version_info[:2] == (2, 7):
            expected.add('config')
        self.assertEqual(names, expected)

    def test_dir_nonrecursive(self):
        d = os.path.join(HERE, 'fake_archives')
        locator = DirectoryLocator(d, recursive=False)
        expected = os.path.join(HERE, 'fake_archives', 'subdir',
                                'subsubdir', 'Flask-0.9.tar.gz')
        def get_path(url):
            t = urlparse(url)
            return url2pathname(t.path)

        for name in ('flask', 'Flask'):
            result = locator.get_project(name)
            self.assertEqual(result, {})
        names = locator.get_distribution_names()
        expected = set(['coverage'])
        self.assertEqual(names, expected)

    def test_path(self):
        fakes = os.path.join(HERE, 'fake_dists')
        sys.path.insert(0, fakes)
        try:
            edp = DistributionPath(include_egg=True)
            locator = DistPathLocator(edp)
            cases = ('babar', 'choxie', 'strawberry', 'towel-stuff',
                     'coconuts-aster', 'bacon', 'grammar', 'truffles',
                     'banana', 'cheese')
            for name in cases:
                d = locator.locate(name, True)
                r = locator.get_project(name)
                self.assertIsNotNone(d)
                self.assertEqual(r, { d.version: d })
            d = locator.locate('nonexistent')
            r = locator.get_project('nonexistent')
            self.assertIsNone(d)
            self.assertFalse(r)

        finally:
            sys.path.pop(0)

    @unittest.skipIf('SKIP_SLOW' in os.environ, 'Skipping slow test')
    def test_aggregation(self):
        d = os.path.join(HERE, 'fake_archives')
        loc1 = DirectoryLocator(d)
        loc2 = SimpleScrapingLocator('https://pypi.python.org/simple/',
                                     timeout=5.0)
        locator = AggregatingLocator(loc1, loc2)
        exp1 = os.path.join(HERE, 'fake_archives', 'subdir',
                            'subsubdir', 'Flask-0.9.tar.gz')
        exp2 = 'https://pypi.python.org/packages/source/F/Flask/Flask-0.9.tar.gz'
        result = locator.get_project('flask')
        self.assertEqual(len(result), 1)
        self.assertIn('0.9', result)
        dist = result['0.9']
        self.assertEqual(dist.name, 'Flask')
        self.assertEqual(dist.version, '0.9')
        scheme, _, path, _, _, _ = urlparse(dist.source_url)
        self.assertEqual(scheme, 'file')
        self.assertEqual(os.path.normcase(url2pathname(path)),
                         os.path.normcase(exp1))
        locator.merge = True
        locator._cache.clear()
        result = locator.get_project('flask')
        self.assertGreater(len(result), 1)
        self.assertIn('0.9', result)
        dist = result['0.9']
        self.assertEqual(dist.name, 'Flask')
        self.assertEqual(dist.version, '0.9')
        self.assertEqual(dist.source_url, exp2)
        return
        # The following code is slow because it has
        # to get all the dist names by scraping :-(
        n1 = loc1.get_distribution_names()
        n2 = loc2.get_distribution_names()
        self.assertEqual(locator.get_distribution_names(), n1 | n2)

    def test_dependency_finder(self):
        locator = AggregatingLocator(
            JSONLocator(),
            SimpleScrapingLocator('https://pypi.python.org/simple/',
                                  timeout=3.0),
            scheme='legacy')
        finder = DependencyFinder(locator)
        dists, problems = finder.find('irc (== 5.0.1)')
        self.assertFalse(problems)
        actual = sorted([d.name for d in dists])
        self.assertEqual(actual, ['hgtools', 'irc',
                                  'pytest-runner'])
        dists, problems = finder.find('irc (== 5.0.1)',
                                      meta_extras=[':test:'])
        self.assertFalse(problems)
        actual = sorted([d.name for d in dists])
        self.assertEqual(actual, ['hgtools', 'irc',
                                  'py', 'pytest',
                                  'pytest-runner'])

        g = make_graph(dists)
        slist, cycle = g.topological_sort()
        self.assertFalse(cycle)
        names = [d.name for d in slist]
        expected = set([
            ('hgtools', 'py', 'pytest', 'pytest-runner', 'irc'),
            ('py', 'hgtools', 'pytest', 'pytest-runner', 'irc'),
            ('hgtools', 'py', 'pytest-runner', 'pytest', 'irc'),
            ('py', 'hgtools', 'pytest-runner', 'pytest', 'irc')
        ])
        self.assertIn(tuple(names), expected)

        # Test with extras
        dists, problems = finder.find('Jinja2 (== 2.6)')
        self.assertFalse(problems)
        actual = sorted([d.name_and_version for d in dists])
        self.assertEqual(actual, ['Jinja2 (2.6)'])
        dists, problems = finder.find('Jinja2 [i18n] (== 2.6)')
        self.assertFalse(problems)
        actual = sorted([d.name_and_version for d in dists])
        self.assertEqual(actual[-2], 'Jinja2 (2.6)')
        self.assertTrue(actual[-1].startswith('pytz ('))
        self.assertTrue(actual[0].startswith('Babel ('))
        actual = [d.build_time_dependency for d in dists]
        self.assertEqual(actual, [False, False, False])

        # Now test with extra in dependency
        locator.clear_cache()
        dummy = make_dist('dummy', '0.1')
        dummy.metadata.run_requires = [{'requires': ['Jinja2 [i18n]']}]
        dists, problems = finder.find(dummy)
        self.assertFalse(problems)
        actual = sorted([d.name_and_version for d in dists])
        self.assertTrue(actual[0].startswith('Babel ('))
        locator.clear_cache()
        dummy.metadata.run_requires = [{'requires': ['Jinja2']}]
        dists, problems = finder.find(dummy)
        self.assertFalse(problems)
        actual = sorted([d.name_and_version for d in dists])
        self.assertTrue(actual[0].startswith('Jinja2 ('))

    def test_get_all_dist_names(self):
        for url in (None, PYPI_RPC_HOST):
            try:
                all_dists = get_all_distribution_names(url)
            except Exception:     # pragma: no cover
                raise unittest.SkipTest('PyPI XML-RPC not available')
            self.assertGreater(len(all_dists), 0)

    def test_url_preference(self):
        cases = (('http://netloc/path', 'https://netloc/path'),
                 ('http://pypi.python.org/path', 'http://netloc/path'),
                 ('http://netloc/B', 'http://netloc/A'))
        for url1, url2 in cases:
            self.assertEqual(default_locator.prefer_url(url1, url2), url1)

    def test_prereleases(self):
        locator = AggregatingLocator(
            JSONLocator(),
            SimpleScrapingLocator('https://pypi.python.org/simple/',
                                  timeout=3.0),
            scheme='legacy')
        REQT = 'SQLAlchemy (>0.5.8, < 0.6)'
        finder = DependencyFinder(locator)
        d = locator.locate(REQT)
        self.assertIsNone(d)
        d = locator.locate(REQT, True)
        self.assertIsNotNone(d)
        self.assertEqual(d.name_and_version, 'SQLAlchemy (0.6beta3)')
        dist = make_dist('dummy', '0.1')
        dist.metadata.run_requires = [{'requires': [REQT]}]
        dists, problems = finder.find(dist, prereleases=True)
        self.assertFalse(problems)
        actual = sorted(dists, key=lambda o: o.name_and_version)
        self.assertEqual(actual[0].name_and_version, 'SQLAlchemy (0.6beta3)')
        dists, problems = finder.find(dist)
        # Test changed since now prereleases as found as a last resort.
        #self.assertEqual(dists, set([dist]))
        #self.assertEqual(len(problems), 1)
        #problem = problems.pop()
        #self.assertEqual(problem, ('unsatisfied', REQT))
        self.assertEqual(dists, set([actual[0], dist]))
        self.assertFalse(problems)

    def test_dist_reqts(self):
        r = 'config (<=0.3.5)'
        dist = default_locator.locate(r)
        self.assertIsNotNone(dist)
        self.assertIsNone(dist.extras)
        self.assertTrue(dist.matches_requirement(r))
        self.assertFalse(dist.matches_requirement('config (0.3.6)'))

    def test_dist_reqts_extras(self):
        r = 'config[doc,test](<=0.3.5)'
        dist = default_locator.locate(r)
        self.assertIsNotNone(dist)
        self.assertTrue(dist.matches_requirement(r))
        self.assertEqual(dist.extras, ['doc', 'test'])

if __name__ == '__main__':  # pragma: no cover
    import logging
    logging.basicConfig(level=logging.DEBUG, filename='test_locators.log',
                        filemode='w', format='%(message)s')
    unittest.main()
