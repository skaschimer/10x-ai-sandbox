# TODOs

## Current Project TODOs

- Put up a warning banner on publicly shared links that says "This is a test for technology evaluation purposes only, this is not a decisional document" Make demo Videos: playground switching sys prompts, transfer sys prompt to custom model with docs
- Cite sources in rag (do this for other models, too):
- Allow bulk select even when nothing is tagged: <https://github.com/GSA-TTS/temp-10x-ai-sandbox/blob/66acbd1b866e9c93edc4457048af323c2fc0a5d0/src/lib/components/workspace/Documents.svelte#L280-L281>
- Models and docs need ownership and visibility in database, owner str, visibility [str]
- gray out vision for custom models that don't have vision
- Ability to share docs/models by pasting an email of another user ("This email is belongs to a sandbox user. They will now have access to the model" / "This email does not belong to a sandbox user"). Probably want comma separation...
- Add http links to Doc upload options, seems mostly done
- Fix tagging ux, add tags should be clickable, should save when you hit save
- Check and batch-tag multiple docs
- documents tab needs a spinner when processing docs
- existing tags should be selectable when adding to docs
- Need initial (Type a message down there 👇 to get started / explain that this is a chat interface) message for new users
- Soft outline around new chat and documents buttons
- Fix translations for docs & more and search your chats, as well as sign in screen
- create a couple default custom prompts shortcuts like /quick-summary ([type something here]) and /quick-summary-from-paste {{clipboard}}
- Unhide Tools from Docs & more layout
- Chroma is kept in ram... need to swap for redisVL
- tell run format to ignore package.json so we don't have to npm install in pre-commit to get formatting to match in the ci check
- change cors all origins to front end and pipelines only

## TODOs Found in Codebase

### Git Hooks

- Replace with appropriate checks (e.g. spell checking)
- Replace with appropriate checks for this patch (e.g. checkpatch.pl)
- Replace with appropriate checks for the whole series (e.g. quick build, coding style checks, etc.)

### Passlib

- Support the drupal phpass variants (see phpass homepage)
- Remove redundant category deprecations
- Verify digest size (if digest is known)
- Find out what crowd's policy is re: unicode
- Find out what grub's policy is re: unicode
- Try to detect incorrect 8bit/wraparound hashes
- Check for 2x support
- Figure out way to skip these tests when not needed
- Would like to implementing verify() directly, to skip need for parsing hash strings
- Would like to dynamically pick this based on system
- Make default block size configurable via using() and deprecatable via .needs_update()
- Could support the optional 'data' parameter
- Switch to working w/ str or unicode
- Factor out variable checksum size support into a mixin
- Add in 'encoding' support once that's finalized in 1.8 / 1.9

### Pandas

- Use inspect.VALUE here, and make the annotations lazily evaluated
- Handle huge files in some other way
- Remove in 1.0 release
- Check -numweeks for next year
- Remove the '$' check after JMESPath supports it
- Make this configurable in the future
- Support text-indent, padding-left -> alignment.indent
- Allow for special properties -excel-pattern-bgcolor and -excel-pattern-type
- Refactor to remove code duplication
- Handle record value which are lists
- Do this timedelta properly in objToJSON.c
- Figure out why these two versions of `meta` dont always match
- Support other fill patterns
- Handle cell width and height: needs support in pandas.io.excel
- Try to consolidate the concat visible rows methods
- Expand to handle datetime to integer conversion
- Handle datetime to integer conversion
- Expand this to handle a default datetime format

### Dateutil

- Check week number 1 of next year as well
- Remove after deprecation period

### Boto3

- Remove the '$' check after JMESPath supports it
- Make this configurable in the future

### Openpyxl

- This can probably be sped up using a regex

### Other

- Support %
- Don't lowercase case sensitive parts of values (strings)
- Hack in buffer capability for pyxlsb
- There is no way to distinguish between floats and datetimes in pyxlsb
- Can we use current color as initial value to comply with CSS standards?
- Warn user if item entered more than once (e.g. "border: red green")
