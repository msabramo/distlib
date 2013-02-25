# -*- coding: utf-8 -*-
#
# Copyright (C) 2012-2013 The Python Software Foundation.
# See LICENSE.txt and CONTRIBUTORS.txt.
#
"""PEP 376 implementation."""

from __future__ import unicode_literals

import base64
import codecs
import hashlib
import logging
import os
import sys
import zipimport

from . import DistlibException
from .compat import StringIO, configparser
from .version import get_scheme, UnsupportedVersionError
from .metadata import Metadata
from .util import (parse_requires, cached_property, get_export_entry,
                   CSVReader, CSVWriter)


__all__ = ['Distribution', 'BaseInstalledDistribution',
           'InstalledDistribution', 'EggInfoDistribution',
           'DistributionPath']


logger = logging.getLogger(__name__)

# TODO update docs

DIST_FILES = ('INSTALLER', 'METADATA', 'RECORD', 'REQUESTED', 'RESOURCES',
              'EXPORTS', 'SHARED')

DISTINFO_EXT = '.dist-info'

class _Cache(object):
    def __init__(self):
        self.name = {}
        self.path = {}
        self.generated = False

    def clear(self):
        self.name.clear()
        self.path.clear()
        self.generated = False

    def add(self, dist):
        if dist.path not in self.path:
            self.path[dist.path] = dist
            self.name.setdefault(dist.key, []).append(dist)

class DistributionPath(object):
    """
    Represents a set of distributions installed on a path (typically sys.path).
    """
    def __init__(self, path=None, include_egg=False):
        if path is None:
            path = sys.path
        self.path = path
        self._include_dist = True
        self._include_egg = include_egg

        self._cache = _Cache()
        self._cache_egg = _Cache()
        self._cache_enabled = True
        self._scheme = get_scheme('default')

    def enable_cache(self):
        """
        Enables the internal cache.

        Note that this function will not clear the cache in any case, for that
        functionality see :meth:`clear_cache`.
        """
        self._cache_enabled = True

    def disable_cache(self):
        """
        Disables the internal cache.

        Note that this function will not clear the cache in any case, for that
        functionality see :meth:`clear_cache`.
        """
        self._cache_enabled = False


    def clear_cache(self):
        """ Clears the internal cache. """
        self._cache.clear()
        self._cache_egg.clear()


    def _yield_distributions(self):
        """
        Yield .dist-info and/or .egg(-info) distributions
        """
        for path in self.path:
            realpath = os.path.realpath(path)
            if not os.path.isdir(realpath):
                continue
            for dir in os.listdir(realpath):
                dist_path = os.path.join(realpath, dir)
                if self._include_dist and dir.endswith(DISTINFO_EXT):
                    yield InstalledDistribution(dist_path, env=self)
                elif self._include_egg and dir.endswith(('.egg-info',
                                                         '.egg')):
                    yield EggInfoDistribution(dist_path, self)

    def _generate_cache(self):
        gen_dist = not self._cache.generated
        gen_egg = self._include_egg and not self._cache_egg.generated
        if gen_dist or gen_egg:
            for dist in self._yield_distributions():
                if isinstance(dist, InstalledDistribution):
                    self._cache.add(dist)
                else:
                    self._cache_egg.add(dist)

            if gen_dist:
                self._cache.generated = True
            if gen_egg:
                self._cache_egg.generated = True

    @classmethod
    def distinfo_dirname(self, name, version):
        """
        The *name* and *version* parameters are converted into their
        filename-escaped form, i.e. any ``'-'`` characters are replaced
        with ``'_'`` other than the one in ``'dist-info'`` and the one
        separating the name from the version number.

        :parameter name: is converted to a standard distribution name by replacing
                         any runs of non- alphanumeric characters with a single
                         ``'-'``.
        :type name: string
        :parameter version: is converted to a standard version string. Spaces
                            become dots, and all other non-alphanumeric characters
                            (except dots) become dashes, with runs of multiple
                            dashes condensed to a single dash.
        :type version: string
        :returns: directory name
        :rtype: string"""
        name = name.replace('-', '_')
        return '-'.join([name, version]) + DISTINFO_EXT


    def get_distributions(self):
        """
        Provides an iterator that looks for ``.dist-info`` directories
        and returns :class:`InstalledDistribution` or
        :class:`EggInfoDistribution` instances for each one of them.

        :rtype: iterator of :class:`InstalledDistribution` and
                :class:`EggInfoDistribution` instances
        """
        if not self._cache_enabled:
            for dist in self._yield_distributions():
                yield dist
        else:
            self._generate_cache()

            for dist in self._cache.path.values():
                yield dist

            if self._include_egg:
                for dist in self._cache_egg.path.values():
                    yield dist


    def get_distribution(self, name):
        """
        Scans all distributions looking for a matching name.

        This function only returns the first result found, as no more than one
        value is expected. If nothing is found, ``None`` is returned.

        :rtype: :class:`InstalledDistribution` or :class:`EggInfoDistribution`
                or ``None``
        """
        result = None
        name = name.lower()
        if not self._cache_enabled:
            for dist in self._yield_distributions():
                if dist.key == name:
                    result = dist
                    break
        else:
            self._generate_cache()

            if name in self._cache.name:
                result = self._cache.name[name][0]
            elif self._include_egg and name in self._cache_egg.name:
                result = self._cache_egg.name[name][0]
        return result


    def obsoletes_distribution(self, name, version=None):
        """
        Iterates over all distributions to find which distributions obsolete
        *name*.

        If a *version* is provided, it will be used to filter the results.

        :type name: string
        :type version: string
        :parameter name: The name to check for being obsoleted.
        """
        for dist in self.get_distributions():
            obsoleted = (dist.metadata['Obsoletes-Dist'] +
                         dist.metadata['Obsoletes'])
            for obs in obsoleted:
                o_components = obs.split(' ', 1)
                if len(o_components) == 1 or version is None:
                    if name == o_components[0]:
                        yield dist
                        break
                else:
                    try:
                        matcher = self._scheme.matcher(obs)
                    except ValueError:
                        raise DistlibException(
                            'distribution %r has ill-formed obsoletes field: '
                            '%r' % (dist.name, obs))
                    if name == o_components[0] and matcher.match(version):
                        yield dist
                        break


    def provides_distribution(self, name, version=None):
        """
        Iterates over all distributions to find which distributions provide *name*.
        If a *version* is provided, it will be used to filter the results.

        This function only returns the first result found, since no more than
        one values are expected. If the directory is not found, returns ``None``.

        :parameter version: a version specifier that indicates the version
                            required, conforming to the format in ``PEP-345``

        :type name: string
        :type version: string
        """
        matcher = None
        if not version is None:
            try:
                matcher = self._scheme.matcher('%s (%s)' % (name, version))
            except ValueError:
                raise DistlibException('invalid name or version: %r, %r' %
                                      (name, version))

        for dist in self.get_distributions():
            provided = dist.provides

            for p in provided:
                p_components = p.rsplit(' ', 1)
                if len(p_components) == 1 or matcher is None:
                    if name == p_components[0]:
                        yield dist
                        break
                else:
                    p_name, p_ver = p_components
                    if len(p_ver) < 2 or p_ver[0] != '(' or p_ver[-1] != ')':
                        raise DistlibException(
                            'distribution %r has invalid Provides field: %r' %
                            (dist.name, p))
                    p_ver = p_ver[1:-1]  # trim off the parenthesis
                    if p_name == name and matcher.match(p_ver):
                        yield dist
                        break

    def get_file_users(self, path):
        """
        Iterates over all distributions to find out which distributions use
        *path*.

        :parameter path: can be a local absolute path or a relative
                         ``'/'``-separated path.
        :type path: string
        :rtype: iterator of :class:`InstalledDistribution` instances
        """
        for dist in self.get_distributions():
            if dist.uses(path):
                yield dist


    def get_file_path(self, name, relative_path):
        """Return the path to a resource file."""
        dist = self.get_distribution(name)
        if dist is None:
            raise LookupError('no distribution named %r found' % name)
        return dist.get_resource_path(relative_path)

    def get_exported_entries(self, category, name=None):
        for dist in self.get_distributions():
            r = dist.exports
            if category in r:
                d = r[category]
                if name is not None:
                    if name in d:
                        yield d[name]
                else:
                    for v in d.values():
                        yield v

class Distribution(object):
    """
    A base class for distributions, whether installed or from indexes.
    Either way, it must have some metadata, so that's all that's needed
    for construction.
    """

    build_time_dependency = False
    """
    Set to True if it's known to be only a build-time dependency (i.e.
    not needed after installation).
    """

    requested = False
    """A boolean that indicates whether the ``REQUESTED`` metadata file is
    present (in other words, whether the package was installed by user
    request or it was installed as a dependency)."""

    extras = None
    """
    Set to a list of requested extras if specified in a requirement.
    """

    def __init__(self, metadata):
        self.metadata = metadata
        self.name = metadata.name
        self.key = self.name.lower()    # for case-insensitive comparisons
        self.version = metadata.version
        self.locator = None
        self.md5_digest = None

    @property
    def download_url(self):
        return self.metadata.download_url

    @property
    def provides(self):
        return set(self.metadata['Provides-Dist']
                   + self.metadata['Provides']
                   + ['%s (%s)' % (self.name, self.version)]
                  )

    @property
    def name_and_version(self):
        return '%s (%s)' % (self.name, self.version)

    @cached_property
    def requires(self):
        return set(self.metadata['Requires-Dist']
                   + self.get_requirements('install')
                   + self.get_requirements('setup')
                   + self.get_requirements('test')
                   )

    def get_requirements(self, key):
        """
        Get the requirements of a particular type
        ('setup', 'install', 'test')
        """
        result = []
        d = self.metadata.dependencies
        if key in d:
            result = d[key]
        return result

    def matches_requirement(self, req):
        scheme = get_scheme(self.metadata.scheme)
        try:
            matcher = scheme.matcher(req)
        except UnsupportedVersionError:
            # XXX compat-mode if cannot read the version
            logger.warning('could not read version %r - using name only',
                           req)
            name = req.split()[0]
            matcher = scheme.matcher(name)

        name = matcher.key   # case-insensitive

        result = False
        # Note this is similar to code in make_graph - to be refactored
        for p in self.provides:
            vm = scheme.matcher(p)
            if vm.key != name:
                continue
            version = vm.exact_version
            assert version
            try:
                result = matcher.match(version)
                break
            except UnsupportedVersionError:
                pass
        return result

    def __repr__(self):
        if self.download_url:
            suffix = ' [%s]' % self.download_url
        else:
            suffix = ''
        return '<Distribution %s (%s)%s>' % (self.name, self.version, suffix)

    def __eq__(self, other):
        if type(other) is not type(self):
            result = False
        else:
            result = (self.name == other.name and
                      self.version == other.version and
                      self.download_url == other.download_url)
        return result

    def __hash__(self):
        return hash(self.name) + hash(self.version) + hash(self.download_url)


class BaseInstalledDistribution(Distribution):

    hasher = None

    def __init__(self, metadata, path, env=None):
        super(BaseInstalledDistribution, self).__init__(metadata)
        self.path = path
        self.dist_path  = env

    def get_hash(self, data, hasher=None):
        """
        Get the hash of some data, using a particular hash algorithm, if
        specified.

        :param data: The data to be hashed.
        :type data: bytes
        :param hasher: The name of a hash implementation, supported by hashlib,
                       or ``None``. Examples of valid values are ``'sha1'``,
                       ``'sha224'``, ``'sha384'``, '``sha256'``, ``'md5'`` and
                       ``'sha512'``. If no hasher is specified, the ``hasher``
                       attribute of the :class:`InstalledDistribution` instance
                       is used. If the hasher is determined to be ``None``, MD5
                       is used as the hashing algorithm.
        :returns: The hash of the data. If a hasher was explicitly specified,
                  the returned hash will be prefixed with the specified hasher
                  followed by '='.
        :rtype: str
        """
        if hasher is None:
            hasher = self.hasher
        if hasher is None:
            hasher = hashlib.md5
            prefix = ''
        else:
            hasher = getattr(hashlib, hasher)
            prefix = '%s=' % self.hasher
        digest = hasher(data).digest()
        digest = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
        return '%s%s' % (prefix, digest)

class InstalledDistribution(BaseInstalledDistribution):
    """Created with the *path* of the ``.dist-info`` directory provided to the
    constructor. It reads the metadata contained in ``METADATA`` when it is
    instantiated., or uses a passed in Metadata instance (useful for when
    dry-run mode is being used)."""

    hasher = 'sha256'

    def __init__(self, path, metadata=None, env=None):
        if env and env._cache_enabled and path in env._cache.path:
            metadata = env._cache.path[path].metadata
        elif metadata is None:
            metadata_path = os.path.join(path, 'METADATA')
            metadata = Metadata(path=metadata_path, scheme='legacy')

        super(InstalledDistribution, self).__init__(metadata, path, env)

        if env and env._cache_enabled:
            env._cache.add(self)

        path = self.get_distinfo_file('REQUESTED')
        self.requested = os.path.exists(path)

    def __repr__(self):
        return '<InstalledDistribution %r %s at %r>' % (
            self.name, self.version, self.path)

    def __str__(self):
        return "%s %s" % (self.name, self.version)

    def _get_records(self):
        results = []
        path = self.get_distinfo_file('RECORD')
        with CSVReader(path) as record_reader:
            # Base location is parent dir of .dist-info dir
            #base_location = os.path.dirname(self.path)
            #base_location = os.path.abspath(base_location)
            for row in record_reader:
                missing = [None for i in range(len(row), 3)]
                path, checksum, size = row + missing
                #if not os.path.isabs(path):
                #    path = path.replace('/', os.sep)
                #    path = os.path.join(base_location, path)
                results.append((path, checksum, size))
        return results

    @cached_property
    def exports(self):
        result = {}
        rf = self.get_distinfo_file('EXPORTS')
        if os.path.exists(rf):
            result = self.read_exports(rf)
        return result

    def read_exports(self, filename=None):
        result = {}
        rf = filename or self.get_distinfo_file('EXPORTS')
        if os.path.exists(rf):
            cp = configparser.ConfigParser()
            cp.read(rf)
            for key in cp.sections():
                result[key] = entries = {}
                for name, value in cp.items(key):
                    s = '%s = %s' % (name, value)
                    entry = get_export_entry(s)
                    assert entry is not None
                    entry.dist = self
                    entries[name] = entry
        return result

    def write_exports(self, exports, filename=None):
        rf = filename or self.get_distinfo_file('EXPORTS')
        cp = configparser.ConfigParser()
        for k, v in exports.items():
            # TODO check k, v for valid values
            cp.add_section(k)
            for entry in v.values():
                if entry.suffix is None:
                    s = entry.prefix
                else:
                    s = '%s:%s' % (entry.prefix, entry.suffix)
                if entry.flags:
                    s = '%s [%s]' % (s, ', '.join(entry.flags))
                cp.set(k, entry.name, s)
        with open(rf, 'w') as f:
            cp.write(f)

    def get_resource_path(self, relative_path):
        path = self.get_distinfo_file('RESOURCES')
        with CSVReader(path) as resources_reader:
            for relative, destination in resources_reader:
                if relative == relative_path:
                    return destination
        raise KeyError('no resource file with relative path %r '
                       'is installed' % relative_path)

    def list_installed_files(self):
        """
        Iterates over the ``RECORD`` entries and returns a tuple
        ``(path, hash, size)`` for each line.

        :returns: iterator of (path, hash, size)
        """
        for result in self._get_records():
            yield result

    def write_installed_files(self, paths, prefix, dry_run=False):
        """
        Writes the ``RECORD`` file, using the ``paths`` iterable passed in. Any
        existing ``RECORD`` file is silently overwritten.

        prefix is used to determine when to write absolute paths.
        """
        prefix = os.path.join(prefix, '')
        base = os.path.dirname(self.path)
        base_under_prefix = base.startswith(prefix)
        base = os.path.join(base, '')
        record_path = os.path.join(self.path, 'RECORD')
        logger.info('creating %s', record_path)
        if dry_run:
            return
        with CSVWriter(record_path) as writer:
            for path in paths:
                if os.path.isdir(path) or path.endswith(('.pyc', '.pyo')):
                    # do not put size and hash, as in PEP-376
                    hash_value = size = ''
                else:
                    size = '%d' % os.path.getsize(path)
                    with open(path, 'rb') as fp:
                        hash_value = self.get_hash(fp.read())
                if path.startswith(base) or (base_under_prefix and
                                                 path.startswith(prefix)):
                    path = os.path.relpath(path, base)
                writer.writerow((path, hash_value, size))

            # add the RECORD file itself
            if record_path.startswith(base):
                record_path = os.path.relpath(record_path, base)
            writer.writerow((record_path, '', ''))

    def check_installed_files(self):
        """
        Checks that the hashes and sizes of the files in ``RECORD`` are
        matched by the files themselves. Returns a (possibly empty) list of
        mismatches. Each entry in the mismatch list will be a tuple consisting
        of the path, 'exists', 'size' or 'hash' according to what didn't match
        (existence is checked first, then size, then hash), the expected
        value and the actual value.
        """
        mismatches = []
        base = os.path.dirname(self.path)
        record_path = os.path.join(self.path, 'RECORD')
        for path, hash_value, size in self.list_installed_files():
            if not os.path.isabs(path):
                path = os.path.join(base, path)
            if path == record_path:
                continue
            if not os.path.exists(path):
                mismatches.append((path, 'exists', True, False))
            elif os.path.isfile(path):
                actual_size = str(os.path.getsize(path))
                if size and actual_size != size:
                    mismatches.append((path, 'size', size, actual_size))
                elif hash_value:
                    if '=' in hash_value:
                        hasher = hash_value.split('=', 1)[0]
                    else:
                        hasher = None

                    with open(path, 'rb') as f:
                        actual_hash = self.get_hash(f.read(), hasher)
                        if actual_hash != hash_value:
                            mismatches.append((path, 'hash', hash_value, actual_hash))
        return mismatches

    @cached_property
    def shared_locations(self):
        result = {}
        shared_path = os.path.join(self.path, 'SHARED')
        if os.path.isfile(shared_path):
            with codecs.open(shared_path, 'r', encoding='utf-8') as f:
                lines = f.read().splitlines()
            for line in lines:
                key, value = line.split('=', 1)
                if key == 'namespace':
                    result.setdefault(key, []).append(value)
                else:
                    result[key] = value
        return result

    def write_shared_locations(self, paths, dry_run=False):
        shared_path = os.path.join(self.path, 'SHARED')
        logger.info('creating %s', shared_path)
        if dry_run:
            return
        lines = []
        for key in ('prefix', 'lib', 'headers', 'scripts', 'data'):
            path = paths[key]
            if os.path.isdir(paths[key]):
                lines.append('%s=%s' % (key,  path))
        for ns in paths.get('namespace', ()):
            lines.append('namespace=%s' % ns)

        with codecs.open(shared_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return shared_path

    def uses(self, path):
        """
        Returns ``True`` if path is listed in ``RECORD``. *path* can be a local
        absolute path or a relative ``'/'``-separated path.

        :rtype: boolean
        """
        base = os.path.dirname(self.path)
        for p, checksum, size in self._get_records():
            if not os.path.isabs(p):
                p = os.path.join(base, p)
            local_absolute = os.path.join(sys.prefix, p)
            if path == p or path == local_absolute:
                return True
        return False

    def get_distinfo_file(self, path):
        """
        Returns a path located under the ``.dist-info`` directory. Returns a
        string representing the path.

        :parameter path: a ``'/'``-separated path relative to the
                         ``.dist-info`` directory or an absolute path;
                         If *path* is an absolute path and doesn't start
                         with the ``.dist-info`` directory path,
                         a :class:`DistlibException` is raised
        :type path: string
        :rtype: str
        """
        # Check if it is an absolute path  # XXX use relpath, add tests
        if path.find(os.sep) >= 0:
            # it's an absolute path?
            distinfo_dirname, path = path.split(os.sep)[-2:]
            if distinfo_dirname != self.path.split(os.sep)[-1]:
                raise DistlibException(
                    'dist-info file %r does not belong to the %r %s '
                    'distribution' % (path, self.name, self.version))

        # The file must be relative
        if path not in DIST_FILES:
            raise DistlibException('invalid path for a dist-info file: %r' %
                                  path)

        return os.path.join(self.path, path)

    def list_distinfo_files(self):
        """
        Iterates over the ``RECORD`` entries and returns paths for each line if
        the path is pointing to a file located in the ``.dist-info`` directory
        or one of its subdirectories.

        :returns: iterator of paths
        """
        base = os.path.dirname(self.path)
        for path, checksum, size in self._get_records():
            # XXX add separator or use real relpath algo
            if not os.path.isabs(path):
                path = os.path.join(base, path)
            if path.startswith(self.path):
                yield path

    def __eq__(self, other):
        return (isinstance(other, InstalledDistribution) and
                self.path == other.path)

    # See http://docs.python.org/reference/datamodel#object.__hash__
    __hash__ = object.__hash__


class EggInfoDistribution(BaseInstalledDistribution):
    """Created with the *path* of the ``.egg-info`` directory or file provided
    to the constructor. It reads the metadata contained in the file itself, or
    if the given path happens to be a directory, the metadata is read from the
    file ``PKG-INFO`` under that directory."""

    requested = True    # as we have no way of knowing, assume it was
    shared_locations = {}

    def __init__(self, path, env=None):
        def set_name_and_version(s, n, v):
            s.name = n
            s.key = n.lower()   # for case-insensitive comparisons
            s.version = v

        self.path = path
        self.dist_path  = env
        if env and env._cache_enabled and path in env._cache_egg.path:
            metadata = env._cache_egg.path[path].metadata
            set_name_and_version(self, metadata['Name'], metadata['Version'])
        else:
            metadata = self._get_metadata(path)

            # Need to be set before caching
            set_name_and_version(self, metadata['Name'], metadata['Version'])

            if env and env._cache_enabled:
                env._cache_egg.add(self)
        super(EggInfoDistribution, self).__init__(metadata, path, env)

    def _get_metadata(self, path):
        requires = None

        if path.endswith('.egg'):
            if os.path.isdir(path):
                meta_path = os.path.join(path, 'EGG-INFO', 'PKG-INFO')
                metadata = Metadata(path=meta_path, scheme='legacy')
                req_path = os.path.join(path, 'EGG-INFO', 'requires.txt')
                requires = parse_requires(req_path)
            else:
                # FIXME handle the case where zipfile is not available
                zipf = zipimport.zipimporter(path)
                fileobj = StringIO(
                    zipf.get_data('EGG-INFO/PKG-INFO').decode('utf8'))
                metadata = Metadata(fileobj=fileobj, scheme='legacy')
                try:
                    requires = zipf.get_data('EGG-INFO/requires.txt')
                except IOError:
                    requires = None
        elif path.endswith('.egg-info'):
            if os.path.isdir(path):
                path = os.path.join(path, 'PKG-INFO')
                req_path = os.path.join(path, 'requires.txt')
                requires = parse_requires(req_path)
            metadata = Metadata(path=path, scheme='legacy')
        else:
            raise ValueError('path must end with .egg-info or .egg, got %r' %
                             path)

        if requires:
            if metadata['Metadata-Version'] == '1.1':
                # we can't have 1.1 metadata *and* Setuptools requires
                for field in ('Obsoletes', 'Requires', 'Provides'):
                    if field in metadata:
                        del metadata[field]
            metadata['Requires-Dist'] += requires
        return metadata

    def __repr__(self):
        return '<EggInfoDistribution %r %s at %r>' % (
            self.name, self.version, self.path)

    def __str__(self):
        return "%s %s" % (self.name, self.version)

    def check_installed_files(self):
        """
        Checks that the hashes and sizes of the files in ``RECORD`` are
        matched by the files themselves. Returns a (possibly empty) list of
        mismatches. Each entry in the mismatch list will be a tuple consisting
        of the path, 'exists', 'size' or 'hash' according to what didn't match
        (existence is checked first, then size, then hash), the expected
        value and the actual value.
        """
        mismatches = []
        record_path = os.path.join(self.path, 'installed-files.txt')
        if os.path.exists(record_path):
            for path, hash, size in self.list_installed_files():
                if path == record_path:
                    continue
                if not os.path.exists(path):
                    mismatches.append((path, 'exists', True, False))
        return mismatches

    def list_installed_files(self, local=False):

        def _md5(path):
            f = open(path, 'rb')
            try:
                content = f.read()
            finally:
                f.close()
            return hashlib.md5(content).hexdigest()

        def _size(path):
            return os.stat(path).st_size

        record_path = os.path.join(self.path, 'installed-files.txt')
        result = []
        if os.path.exists(record_path):
            with codecs.open(record_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    p = os.path.normpath(os.path.join(self.path, line))
                    # "./" is present as a marker between installed files
                    # and installation metadata files
                    if not os.path.isdir(p):
                        result.append((p, _md5(p), _size(p)))
            result.append((record_path, None, None))
        return result

    def list_distinfo_files(self, local=False):
        """
        Iterates over the ``installed-files.txt`` entries and returns paths for
        each line if the path is pointing to a file located in the
        ``.egg-info`` directory or one of its subdirectories.

        :parameter local: If *local* is ``True``, each returned path is
                          transformed into a local absolute path. Otherwise the
                          raw value from ``installed-files.txt`` is returned.
        :type local: boolean
        :returns: iterator of paths
        """
        record_path = os.path.join(self.path, 'installed-files.txt')
        skip = True
        with codecs.open(record_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line == './':
                    skip = False
                    continue
                if not skip:
                    p = os.path.normpath(os.path.join(self.path, line))
                    if p.startswith(self.path):
                        if local:
                            yield p
                        else:
                            yield line

    def uses(self, path):
        return False

    def __eq__(self, other):
        return (isinstance(other, EggInfoDistribution) and
                self.path == other.path)

    # See http://docs.python.org/reference/datamodel#object.__hash__
    __hash__ = object.__hash__

class DependencyGraph(object):
    """
    Represents a dependency graph between distributions.

    The dependency relationships are stored in an ``adjacency_list`` that maps
    distributions to a list of ``(other, label)`` tuples where  ``other``
    is a distribution and the edge is labeled with ``label`` (i.e. the version
    specifier, if such was provided). Also, for more efficient traversal, for
    every distribution ``x``, a list of predecessors is kept in
    ``reverse_list[x]``. An edge from distribution ``a`` to
    distribution ``b`` means that ``a`` depends on ``b``. If any missing
    dependencies are found, they are stored in ``missing``, which is a
    dictionary that maps distributions to a list of requirements that were not
    provided by any other distributions.
    """

    def __init__(self):
        self.adjacency_list = {}
        self.reverse_list = {}
        self.missing = {}

    def add_distribution(self, distribution):
        """Add the *distribution* to the graph.

        :type distribution: :class:`distutils2.database.InstalledDistribution`
                            or :class:`distutils2.database.EggInfoDistribution`
        """
        self.adjacency_list[distribution] = []
        self.reverse_list[distribution] = []
        #self.missing[distribution] = []

    def add_edge(self, x, y, label=None):
        """Add an edge from distribution *x* to distribution *y* with the given
        *label*.

        :type x: :class:`distutils2.database.InstalledDistribution` or
                 :class:`distutils2.database.EggInfoDistribution`
        :type y: :class:`distutils2.database.InstalledDistribution` or
                 :class:`distutils2.database.EggInfoDistribution`
        :type label: ``str`` or ``None``
        """
        self.adjacency_list[x].append((y, label))
        # multiple edges are allowed, so be careful
        if x not in self.reverse_list[y]:
            self.reverse_list[y].append(x)

    def add_missing(self, distribution, requirement):
        """
        Add a missing *requirement* for the given *distribution*.

        :type distribution: :class:`distutils2.database.InstalledDistribution`
                            or :class:`distutils2.database.EggInfoDistribution`
        :type requirement: ``str``
        """
        logger.debug('%s missing %r', distribution, requirement)
        self.missing.setdefault(distribution, []).append(requirement)

    def _repr_dist(self, dist):
        return '%s %s' % (dist.name, dist.version)

    def repr_node(self, dist, level=1):
        """Prints only a subgraph"""
        output = [self._repr_dist(dist)]
        for other, label in self.adjacency_list[dist]:
            dist = self._repr_dist(other)
            if label is not None:
                dist = '%s [%s]' % (dist, label)
            output.append('    ' * level + str(dist))
            suboutput = self.repr_node(other, level + 1)
            subs = suboutput.split('\n')
            output.extend(subs[1:])
        return '\n'.join(output)

    def to_dot(self, f, skip_disconnected=True):
        """Writes a DOT output for the graph to the provided file *f*.

        If *skip_disconnected* is set to ``True``, then all distributions
        that are not dependent on any other distribution are skipped.

        :type f: has to support ``file``-like operations
        :type skip_disconnected: ``bool``
        """
        disconnected = []

        f.write("digraph dependencies {\n")
        for dist, adjs in self.adjacency_list.items():
            if len(adjs) == 0 and not skip_disconnected:
                disconnected.append(dist)
            for other, label in adjs:
                if not label is None:
                    f.write('"%s" -> "%s" [label="%s"]\n' %
                                                (dist.name, other.name, label))
                else:
                    f.write('"%s" -> "%s"\n' % (dist.name, other.name))
        if not skip_disconnected and len(disconnected) > 0:
            f.write('subgraph disconnected {\n')
            f.write('label = "Disconnected"\n')
            f.write('bgcolor = red\n')

            for dist in disconnected:
                f.write('"%s"' % dist.name)
                f.write('\n')
            f.write('}\n')
        f.write('}\n')

    def topological_sort(self):
        result = []
        # Make a shallow copy of the adjacency list
        alist = {}
        for k, v in self.adjacency_list.items():
            alist[k] = v[:]
        while True:
            # See what we can remove in this run
            to_remove = []
            for k, v in list(alist.items())[:]:
                if not v:
                    to_remove.append(k)
                    del alist[k]
            if not to_remove:
                # What's left in alist (if anything) is a cycle.
                break
            # Remove from the adjacency list of others
            for k, v in alist.items():
                alist[k] = [(d, r) for d, r in v if d not in to_remove]
            logger.debug('Moving to result: %s',
                ['%s (%s)' % (d.name, d.version) for d in to_remove])
            result.extend(to_remove)
        return result, list(alist.keys())

    def __repr__(self):
        """Representation of the graph"""
        output = []
        for dist, adjs in self.adjacency_list.items():
            output.append(self.repr_node(dist))
        return '\n'.join(output)


def make_graph(dists, scheme='default'):
    """Makes a dependency graph from the given distributions.

    :parameter dists: a list of distributions
    :type dists: list of :class:`distutils2.database.InstalledDistribution` and
                 :class:`distutils2.database.EggInfoDistribution` instances
    :rtype: a :class:`DependencyGraph` instance
    """
    scheme = get_scheme(scheme)
    graph = DependencyGraph()
    provided = {}  # maps names to lists of (version, dist) tuples

    # first, build the graph and find out what's provided
    for dist in dists:
        graph.add_distribution(dist)

        for p in dist.provides:
            comps = p.strip().rsplit(" ", 1)
            name = comps[0]
            version = None
            if len(comps) == 2:
                version = comps[1]
                if len(version) < 3 or version[0] != '(' or version[-1] != ')':
                    logger.warning('distribution %r has ill-formed '
                                   'provides field: %r', dist.name, p)
                    continue
                    # don't raise an exception. Legacy installed distributions
                    # could have all manner of metadata
                    #raise DistlibException('distribution %r has ill-formed '
                    #                       'provides field: %r' % (dist.name, p))
                version = version[1:-1]  # trim off parenthesis
            # Add name in lower case for case-insensitivity
            name = name.lower()
            logger.debug('Add to provided: %s, %s, %s', name, version, dist)
            provided.setdefault(name, []).append((version, dist))

    # now make the edges
    for dist in dists:
        # need to leave this in because tests currently rely on it ...
        requires = dist.metadata['Requires-Dist']
        if not requires:
            requires = (dist.get_requirements('install') +
                        dist.get_requirements('setup'))
        for req in requires:
            try:
                matcher = scheme.matcher(req)
            except UnsupportedVersionError:
                # XXX compat-mode if cannot read the version
                logger.warning('could not read version %r - using name only',
                               req)
                name = req.split()[0]
                matcher = scheme.matcher(name)

            name = matcher.key   # case-insensitive

            matched = False
            if name in provided:
                for version, provider in provided[name]:
                    try:
                        match = matcher.match(version)
                    except UnsupportedVersionError:
                        match = False

                    if match:
                        graph.add_edge(dist, provider, req)
                        matched = True
                        break
            if not matched:
                graph.add_missing(dist, req)
    return graph


def get_dependent_dists(dists, dist):
    """Recursively generate a list of distributions from *dists* that are
    dependent on *dist*.

    :param dists: a list of distributions
    :param dist: a distribution, member of *dists* for which we are interested
    """
    if dist not in dists:
        raise ValueError('given distribution %r is not a member of the list' %
                         dist.name)
    graph = make_graph(dists)

    dep = [dist]  # dependent distributions
    todo = graph.reverse_list[dist]  # list of nodes we should inspect

    while todo:
        d = todo.pop()
        dep.append(d)
        for succ in graph.reverse_list[d]:
            if succ not in dep:
                todo.append(succ)

    dep.pop(0)  # remove dist from dep, was there to prevent infinite loops
    return dep

def get_required_dists(dists, dist):
    """Recursively generate a list of distributions from *dists* that are
    required by *dist*.

    :param dists: a list of distributions
    :param dist: a distribution, member of *dists* for which we are interested
    """
    if dist not in dists:
        raise ValueError('given distribution %r is not a member of the list' %
                         dist.name)
    graph = make_graph(dists)

    req = []  # required distributions
    todo = graph.adjacency_list[dist]  # list of nodes we should inspect

    while todo:
        d = todo.pop()[0]
        req.append(d)
        for pred in graph.adjacency_list[d]:
            if pred not in req:
                todo.append(pred)

    return req
