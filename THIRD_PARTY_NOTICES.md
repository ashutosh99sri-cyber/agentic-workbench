# Third-party notices

Original project contributions use [Apache-2.0](LICENSE). The materials below
retain their upstream notices. Their inclusion does not establish ownership of
the project's original contributions or change the upstream license terms.

## Ponytail: adapted engineering instructions

The decision order and related engineering guidance in
`src/agentic_workbench/bundled_skills/engineering/SKILL.md` are adapted from
[Ponytail](https://github.com/DietrichGebert/ponytail). The adaptation is recorded
in that skill's `skill.toml` and [source provenance](docs/design/SOURCE-PROVENANCE.md).
The complete upstream application is not bundled. This notice conservatively
preserves the upstream permission for the adapted instructions.

```text
MIT License

Copyright (c) 2026 DietrichGebert

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## more-itertools: historical corpus source snippet

`evaluations/python/negative-controls.json` contains a small source snippet from
`more_itertools/more.py` in its `needle` and `replacement` fields. The corpus
records [more-itertools](https://github.com/more-itertools/more-itertools) source
commits and license-file hashes in `evaluations/python/provenance.json` and
`archives.lock.json`. The complete upstream project is not bundled in this
repository. The notice below is retained for the copied snippet.

```text
Copyright (c) 2012 Erik Rose

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Dependencies and external evaluation archives

`uv.lock` and `adapters/node/package-lock.json` pin external packages; a lockfile
is not a copy of each package's source or a replacement for its license files.
The Python and Node distributions declare dependencies separately. Retain the
packages' own licenses and applicable notices when distributing an environment,
container, executable bundle, or other artifact that includes them.

In particular, `pathspec==1.1.1` uses MPL-2.0. Its covered files retain that
license, including its source availability obligations when distributing an
executable form. See the [licensing guide](docs/public/LICENSING.md) for the
redistribution boundary and the remaining conditional-package review.

The historical Python corpus pins external more-itertools (MIT), Click
(BSD-3-Clause), and packaging (Apache-2.0 OR BSD-2-Clause) archives. These
archives are fetched separately and retain their upstream license files.
If redistributing an archive, prepared source tree, or copied upstream material,
preserve the applicable original license and notices; this file does not
replace them. See the [corpus provenance](evaluations/python/README.md).
