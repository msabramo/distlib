Change log for ``distlib``
==========================

0.1.1
-----

Released: not yet.

- database

    - Updated requirements logic to use extras and environment markers.

- locators

    - Added method to clear locator caches.

    - Added the ability to skip pre-releases.

- metadata

    - Updated to handle most 2.0 fields, though PEP 426 is still a draft.

    - Added the option to skip unset fields when writing.

- scripts

    - Fixed bug which prevented writing shebang lines correctly on Windows.

- util

    - Made get_cache_base more useful by parametrising the suffix to use.

    - Fixed a bug when reading CSV streams from .zip files under 3.x.

- version

    - Added is_prerelease property to versions.

    - Moved to PEP 426 version formats and sorting.

- wheel

    - Fixed CSV stream reading under 3.x and handled UTF-8 in zip entries
      correctly.

    - Added metadata and info properties, and updated the install method to
      return the installed distribution.

    - Added mount/unmount functionality.

- docs

    - Numerous documentation updates, not detailed further here.

- tests

    - Numerous test refinements, not detailed further here.


0.1.0
-----

Released: 2013-03-02

- Initial release.