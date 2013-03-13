# -*- coding: utf-8 -*-
#
# Copyright (C) 2012-2013 The Python Software Foundation.
# See LICENSE.txt and CONTRIBUTORS.txt.
#
"""Tests for distlib.metadata."""
from __future__ import unicode_literals

import os
import sys
import codecs
from textwrap import dedent

from compat import unittest

from distlib.compat import StringIO
from distlib.metadata import (Metadata, PKG_INFO_PREFERRED_VERSION,
                             MetadataConflictError, MetadataMissingError,
                             MetadataUnrecognizedVersionError, _ATTR2FIELD)

from support import (LoggingCatcher, TempdirManager, EnvironRestorer,
                      requires_docutils)


HERE = os.path.abspath(os.path.dirname(__file__))

class MetadataTestCase(LoggingCatcher, TempdirManager,
                       EnvironRestorer, unittest.TestCase):

    maxDiff = None
    restore_environ = ['HOME']

    def setUp(self):
        super(MetadataTestCase, self).setUp()
        self.argv = sys.argv, sys.argv[:]

    def tearDown(self):
        sys.argv = self.argv[0]
        sys.argv[:] = self.argv[1]
        super(MetadataTestCase, self).tearDown()

    ####  Test various methods of the Metadata class

    def get_file_contents(self, name):
        name = os.path.join(HERE, name)
        f = codecs.open(name, 'r', encoding='utf-8')
        try:
            contents = f.read() % sys.platform
        finally:
            f.close()
        return contents

    def test_instantiation(self):
        PKG_INFO = os.path.join(HERE, 'PKG-INFO')
        f = codecs.open(PKG_INFO, 'r', encoding='utf-8')
        try:
            contents = f.read()
        finally:
            f.close()

        fp = StringIO(contents)

        m = Metadata()
        self.assertRaises(MetadataUnrecognizedVersionError, m.items)

        m = Metadata(PKG_INFO)
        self.assertEqual(len(m.items()), 22)

        m = Metadata(fileobj=fp)
        self.assertEqual(len(m.items()), 22)

        m = Metadata(mapping=dict(name='Test', version='1.0'))
        self.assertEqual(len(m.items()), 17)

        d = dict(m.items())
        self.assertRaises(TypeError, Metadata,
                          PKG_INFO, fileobj=fp)
        self.assertRaises(TypeError, Metadata,
                          PKG_INFO, mapping=d)
        self.assertRaises(TypeError, Metadata,
                          fileobj=fp, mapping=d)
        self.assertRaises(TypeError, Metadata,
                          PKG_INFO, mapping=m, fileobj=fp)

    def test_metadata_markers(self):
        # see if we can be platform-aware
        content = self.get_file_contents('PKG-INFO')
        metadata = Metadata(platform_dependent=True)

        metadata.read_file(StringIO(content))
        self.assertEqual(metadata['Requires-Dist'], ['bar'])
        metadata['Name'] = "baz; sys.platform == 'blah'"
        # FIXME is None or 'UNKNOWN' correct here?
        # where is that documented?
        self.assertEqual(metadata['Name'], None)

        # test with context
        context = {'sys.platform': 'okook'}
        metadata = Metadata(platform_dependent=True, execution_context=context)
        metadata.read_file(StringIO(content))
        self.assertEqual(metadata['Requires-Dist'], ['foo'])

    def test_mapping_api(self):
        content = self.get_file_contents('PKG-INFO')
        metadata = Metadata(fileobj=StringIO(content))
        self.assertIn('Version', metadata.keys())
        self.assertIn('0.5', metadata.values())
        self.assertIn(('Version', '0.5'), metadata.items())

        metadata.update({'version': '0.6'})
        self.assertEqual(metadata['Version'], '0.6')
        metadata.update([('version', '0.7')])
        self.assertEqual(metadata['Version'], '0.7')
        # use a kwarg to update
        metadata.update(version='0.6')
        self.assertEqual(metadata['Version'], '0.6')

        # make sure update method checks values like the set method does
        metadata.update({'version': '1--2'})
        self.assertEqual(len(self.get_logs()), 1)

        self.assertEqual(list(metadata), metadata.keys())

    def test_attribute_access(self):
        content = self.get_file_contents('PKG-INFO')
        metadata = Metadata(fileobj=StringIO(content))
        for attr in _ATTR2FIELD:
            self.assertEqual(getattr(metadata, attr), metadata[attr])

    def test_read_metadata(self):
        fields = {'name': 'project',
                  'version': '1.0',
                  'description': 'desc',
                  'summary': 'xxx',
                  'download_url': 'http://example.com',
                  'keywords': ['one', 'two'],
                  'requires_dist': ['foo']}

        metadata = Metadata(mapping=fields)
        PKG_INFO = StringIO()
        metadata.write_file(PKG_INFO)
        PKG_INFO.seek(0)

        metadata = Metadata(fileobj=PKG_INFO)

        self.assertEqual(metadata['name'], 'project')
        self.assertEqual(metadata['version'], '1.0')
        self.assertEqual(metadata['summary'], 'xxx')
        self.assertEqual(metadata['download_url'], 'http://example.com')
        self.assertEqual(metadata['keywords'], ['one', 'two'])
        self.assertEqual(metadata['platform'], [])
        self.assertEqual(metadata['obsoletes'], [])
        self.assertEqual(metadata['requires-dist'], ['foo'])

    def test_write_metadata(self):
        # check support of non-ASCII values
        tmp_dir = self.mkdtemp()
        my_file = os.path.join(tmp_dir, 'f')

        metadata = Metadata(mapping={'author': 'Mister Café',
                                     'name': 'my.project',
                                     'author': 'Café Junior',
                                     'summary': 'Café torréfié',
                                     'description': 'Héhéhé',
                                     'keywords': ['café', 'coffee']})
        metadata.write(my_file)

        # the file should use UTF-8
        metadata2 = Metadata()
        fp = codecs.open(my_file, encoding='utf-8')
        try:
            metadata2.read_file(fp)
        finally:
            fp.close()

        # XXX when keywords are not defined, metadata will have
        # 'Keywords': [] but metadata2 will have 'Keywords': ['']
        # because of a value.split(',') in Metadata.get
        self.assertEqual(metadata.items(), metadata2.items())

        # ASCII also works, it's a subset of UTF-8
        metadata = Metadata(mapping={'author': 'Mister Cafe',
                                     'name': 'my.project',
                                     'author': 'Cafe Junior',
                                     'summary': 'Cafe torrefie',
                                     'description': 'Hehehe'})
        metadata.write(my_file)

        metadata2 = Metadata()
        fp = codecs.open(my_file, encoding='utf-8')
        try:
            metadata2.read_file(fp)
        finally:
            fp.close()

    def test_metadata_read_write(self):
        PKG_INFO = os.path.join(HERE, 'PKG-INFO')
        metadata = Metadata(PKG_INFO)
        out = StringIO()
        metadata.write_file(out)

        out.seek(0)
        res = Metadata()
        res.read_file(out)
        self.assertEqual(metadata.values(), res.values())

    ####  Test checks

    def test_check_version(self):
        metadata = Metadata()
        metadata['Name'] = 'vimpdb'
        metadata['Home-page'] = 'http://pypi.python.org'
        metadata['Author'] = 'Monty Python'
        metadata.docutils_support = False
        missing, warnings = metadata.check()
        self.assertEqual(missing, ['Version'])

    def test_check_version_strict(self):
        metadata = Metadata()
        metadata['Name'] = 'vimpdb'
        metadata['Home-page'] = 'http://pypi.python.org'
        metadata['Author'] = 'Monty Python'
        metadata.docutils_support = False
        self.assertRaises(MetadataMissingError, metadata.check, strict=True)

    def test_check_name(self):
        metadata = Metadata()
        metadata['Version'] = '1.0'
        metadata['Home-page'] = 'http://pypi.python.org'
        metadata['Author'] = 'Monty Python'
        metadata.docutils_support = False
        missing, warnings = metadata.check()
        self.assertEqual(missing, ['Name'])

    def test_check_name_strict(self):
        metadata = Metadata()
        metadata['Version'] = '1.0'
        metadata['Home-page'] = 'http://pypi.python.org'
        metadata['Author'] = 'Monty Python'
        metadata.docutils_support = False
        self.assertRaises(MetadataMissingError, metadata.check, strict=True)

    def test_check_author(self):
        metadata = Metadata()
        metadata['Version'] = '1.0'
        metadata['Name'] = 'vimpdb'
        metadata['Home-page'] = 'http://pypi.python.org'
        metadata.docutils_support = False
        missing, warnings = metadata.check()
        self.assertEqual(missing, ['Author'])

    def test_check_homepage(self):
        metadata = Metadata()
        metadata['Version'] = '1.0'
        metadata['Name'] = 'vimpdb'
        metadata['Author'] = 'Monty Python'
        metadata.docutils_support = False
        missing, warnings = metadata.check()
        self.assertEqual(missing, ['Home-page'])

    def test_check_matchers(self):
        metadata = Metadata()
        metadata['Version'] = 'rr'
        metadata['Name'] = 'vimpdb'
        metadata['Home-page'] = 'http://pypi.python.org'
        metadata['Author'] = 'Monty Python'
        metadata['Requires-dist'] = ['Foo (a)']
        metadata['Obsoletes-dist'] = ['Foo (a)']
        metadata['Provides-dist'] = ['Foo (a)']
        missing, warnings = metadata.check()
        self.assertEqual(len(warnings), 4)

    ####  Test fields and metadata versions

    def test_metadata_versions(self):
        metadata = Metadata(mapping={'name': 'project', 'version': '1.0'})
        self.assertEqual(metadata['Metadata-Version'],
                         PKG_INFO_PREFERRED_VERSION)
        self.assertNotIn('Provides', metadata)
        self.assertNotIn('Requires', metadata)
        self.assertNotIn('Obsoletes', metadata)

        metadata['Classifier'] = ['ok']
        metadata.set_metadata_version()
        self.assertEqual(metadata['Metadata-Version'], '1.1')

        metadata = Metadata()
        metadata['Download-URL'] = 'ok'
        metadata.set_metadata_version()
        self.assertEqual(metadata['Metadata-Version'], '1.1')

        metadata = Metadata()
        metadata['Obsoletes'] = 'ok'
        metadata.set_metadata_version()
        self.assertEqual(metadata['Metadata-Version'], '1.1')

        del metadata['Obsoletes']
        metadata['Obsoletes-Dist'] = 'ok'
        metadata.set_metadata_version()
        self.assertEqual(metadata['Metadata-Version'], '1.2')
        metadata.set('Obsoletes', 'ok')
        self.assertRaises(MetadataConflictError,
                          metadata.set_metadata_version)

        del metadata['Obsoletes']
        del metadata['Obsoletes-Dist']
        metadata.set_metadata_version()
        metadata['Version'] = '1'
        self.assertEqual(metadata['Metadata-Version'], '1.1')

        # make sure the _best_version function works okay with
        # non-conflicting fields from 1.1 and 1.2 (i.e. we want only the
        # requires/requires-dist and co. pairs to cause a conflict, not all
        # fields in _314_MARKERS)
        metadata = Metadata()
        metadata['Requires-Python'] = '3'
        metadata['Classifier'] = ['Programming language :: Python :: 3']
        metadata.set_metadata_version()
        self.assertEqual(metadata['Metadata-Version'], '1.2')

        PKG_INFO = os.path.join(HERE, 'SETUPTOOLS-PKG-INFO')
        metadata = Metadata(PKG_INFO)
        self.assertEqual(metadata['Metadata-Version'], '1.1')

        PKG_INFO = os.path.join(HERE, 'SETUPTOOLS-PKG-INFO2')
        metadata = Metadata(PKG_INFO)
        self.assertEqual(metadata['Metadata-Version'], '1.1')

        # make sure an empty list for Obsoletes and Requires-dist gets ignored
        metadata['Obsoletes'] = []
        metadata['Requires-dist'] = []
        metadata.set_metadata_version()
        self.assertEqual(metadata['Metadata-Version'], '1.1')

        # Update the _fields dict directly to prevent 'Metadata-Version'
        # from being updated by the _set_best_version() method.
        metadata._fields['Metadata-Version'] = '1.618'
        self.assertRaises(MetadataUnrecognizedVersionError, metadata.keys)

    def test_version(self):
        Metadata(mapping={'author': 'xxx',
                          'name': 'xxx',
                          'version': 'xxx',
                          'home_page': 'xxxx'})
        logs = self.get_logs()
        self.assertEqual(1, len(logs))
        self.assertIn('not a valid version', logs[0])

    def test_description(self):
        content = self.get_file_contents('PKG-INFO')
        metadata = Metadata()
        metadata.read_file(StringIO(content))

        # see if we can read the description now
        DESC = os.path.join(HERE, 'LONG_DESC.txt')
        f = open(DESC)
        try:
            wanted = f.read()
        finally:
            f.close()
        self.assertEqual(wanted, metadata['Description'])

        # save the file somewhere and make sure we can read it back
        out = StringIO()
        metadata.write_file(out)
        out.seek(0)

        out.seek(0)
        metadata = Metadata()
        metadata.read_file(out)
        self.assertEqual(wanted, metadata['Description'])

    def test_description_folding(self):
        # make sure the indentation is preserved
        out = StringIO()
        desc = dedent("""\
        example::
              We start here
            and continue here
          and end here.
        """)

        metadata = Metadata()
        metadata['description'] = desc
        metadata.write_file(out)

        folded_desc = desc.replace('\n', '\n' + (7 * ' ') + '|')
        self.assertIn(folded_desc, out.getvalue())

    @requires_docutils
    def test_description_invalid_rst(self):
        # make sure bad rst is well handled in the description attribute
        metadata = Metadata()
        description = ':funkie:`str`'  # mimic Sphinx-specific markup
        metadata['description'] = description
        missing, warnings = metadata.check(restructuredtext=True)
        warning = warnings[0][1]
        self.assertIn('funkie', warning)

    def test_project_url(self):
        metadata = Metadata()
        metadata['Project-URL'] = [('one', 'http://ok')]
        self.assertEqual(metadata['Project-URL'], [('one', 'http://ok')])
        metadata.set_metadata_version()
        self.assertEqual(metadata['Metadata-Version'], '1.2')

        # make sure this particular field is handled properly when written
        fp = StringIO()
        metadata.write_file(fp)
        self.assertIn('Project-URL: one,http://ok', fp.getvalue().split('\n'))

        fp.seek(0)
        metadata = Metadata()
        metadata.read_file(fp)
        self.assertEqual(metadata['Project-Url'], [('one', 'http://ok')])

    # TODO copy tests for v1.1 requires, obsoletes and provides from distutils
    # (they're useless but we support them so we should test them anyway)

    def test_provides_dist(self):
        fields = {'name': 'project',
                  'version': '1.0',
                  'provides_dist': ['project', 'my.project']}
        metadata = Metadata(mapping=fields)
        self.assertEqual(metadata['Provides-Dist'],
                         ['project', 'my.project'])
        self.assertEqual(metadata['Metadata-Version'], '1.2', metadata)
        self.assertNotIn('Requires', metadata)
        self.assertNotIn('Obsoletes', metadata)

    @unittest.skip('needs to be implemented')
    def test_provides_illegal(self):
        # TODO check the versions (like distutils does for old provides field)
        self.assertRaises(ValueError, Metadata,
                          mapping={'name': 'project',
                                   'version': '1.0',
                                   'provides_dist': ['my.pkg (splat)']})

    def test_requires_dist(self):
        fields = {'name': 'project',
                  'version': '1.0',
                  'requires_dist': ['other', 'another (==1.0)']}
        metadata = Metadata(mapping=fields)
        self.assertEqual(metadata['Requires-Dist'],
                         ['other', 'another (==1.0)'])
        self.assertEqual(metadata['Metadata-Version'], '1.2')
        self.assertNotIn('Provides', metadata)
        self.assertEqual(metadata['Requires-Dist'],
                         ['other', 'another (==1.0)'])
        self.assertNotIn('Obsoletes', metadata)

        # make sure write_file uses one RFC 822 header per item
        fp = StringIO()
        metadata.write_file(fp)
        lines = fp.getvalue().split('\n')
        self.assertIn('Requires-Dist: other', lines)
        self.assertIn('Requires-Dist: another (==1.0)', lines)

        # test warnings for invalid version constraints
        # XXX this would cause no warnings if we used update (or the mapping
        # argument of the constructor), see comment in Metadata.update
        metadata = Metadata()
        metadata['Requires-Dist'] = 'Funky (Groovie)'
        metadata['Requires-Python'] = '1-4'
        self.assertEqual(len(self.get_logs()), 2)

        # test multiple version matches
        metadata = Metadata()

        # XXX check PEP and see if 3 == 3.0
        metadata['Requires-Python'] = '>=2.6, <3.0'
        metadata['Requires-Dist'] = ['Foo (>=2.6, <3.0)']
        self.assertEqual(self.get_logs(), [])

    @unittest.skip('needs to be implemented')
    def test_requires_illegal(self):
        self.assertRaises(ValueError, Metadata,
                          mapping={'name': 'project',
                                   'version': '1.0',
                                   'requires': ['my.pkg (splat)']})

    def test_obsoletes_dist(self):
        fields = {'name': 'project',
                  'version': '1.0',
                  'obsoletes_dist': ['other', 'another (<1.0)']}
        metadata = Metadata(mapping=fields)
        self.assertEqual(metadata['Obsoletes-Dist'],
                         ['other', 'another (<1.0)'])
        self.assertEqual(metadata['Metadata-Version'], '1.2')
        self.assertNotIn('Provides', metadata)
        self.assertNotIn('Requires', metadata)
        self.assertEqual(metadata['Obsoletes-Dist'],
                         ['other', 'another (<1.0)'])

    @unittest.skip('needs to be implemented')
    def test_obsoletes_illegal(self):
        self.assertRaises(ValueError, Metadata,
                          mapping={'name': 'project',
                                   'version': '1.0',
                                   'obsoletes': ['my.pkg (splat)']})

    def test_fullname(self):
        md = Metadata()
        md['Name'] = 'a b c'
        md['Version'] = '1 0 0'
        s = md.get_fullname()
        self.assertEqual(s, 'a b c-1 0 0')
        s = md.get_fullname(True)
        self.assertEqual(s, 'a-b-c-1.0.0')

    def test_fields(self):
        md = Metadata()
        self.assertTrue(md.is_multi_field('Requires-Dist'))
        self.assertFalse(md.is_multi_field('Name'))
        self.assertTrue(md.is_field('Obsoleted-By'))
        self.assertFalse(md.is_field('Frobozz'))

if __name__ == '__main__':  # pragma: no cover
    unittest.main()
