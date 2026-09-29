"""Exercise the actual Alpine copy handler without a browser dependency."""

from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest


class CopyButton(HTMLParser):
    handler = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "button" and "@click" in attrs:
            self.handler = attrs["@click"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node needed for isolated JS check")
@pytest.mark.parametrize("mode", ["success", "denied", "unsupported"])
def test_copy_response_handler(mode):
    parser = CopyButton()
    parser.feed((Path(__file__).parents[1] / "templates/_mcp_result.html").read_text())
    assert parser.handler
    script = """
import assert from 'node:assert/strict';
const mode = MODE;
const state = {copying: false, copyStatus: 'old result'};
const text = JSON.stringify({notes: '<script> & quotes "', data: 'x'.repeat(20000)});
let copied;
const navigator = mode === 'unsupported' ? {} : {clipboard: {writeText: async value => {
    if (mode === 'denied') throw new Error('Permission denied');
    copied = value;
}}};
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const click = new AsyncFunction('navigator', '$refs', 'with(this) {' + HANDLER + '}');
await click.call(state, navigator, {evidence: {textContent: text}});
assert.equal(state.copying, false);
if (mode === 'success') {
    assert.equal(copied, text);
    assert.equal(state.copyStatus, 'Response copied.');
} else {
    assert.equal(copied, undefined);
    assert.match(state.copyStatus, /Could not copy/);
}
""".replace("MODE", json.dumps(mode)).replace("HANDLER", json.dumps(parser.handler))
    subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True)
