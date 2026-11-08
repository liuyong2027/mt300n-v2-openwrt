"""Keep SSR Plus+ "Start Probe" reachable on narrow phone viewports.

Upstream places the toggle in the last table header cell; LuCI's responsive
card layout hides that header below ~768px. Move the same button into a
full-width toolbar above the node table on small screens; desktop stays put.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Pinned probe-mobile source changed: ' + repr(old[:90]))
    return text.replace(old, new, 1)


HELPERS = '''
			const ensureProbeToolbar = () => {
				let bar = document.getElementById("ssr-probe-toolbar");
				if (bar) {
					return bar;
				}
				const servers = document.getElementById("cbi-shadowsocksr-servers");
				if (!servers) {
					return null;
				}
				bar = document.createElement("div");
				bar.id = "ssr-probe-toolbar";
				bar.className = "ssr-probe-toolbar";
				bar.style.cssText = "display:none;width:100%;box-sizing:border-box;margin:0.5em 0;";
				const table = servers.querySelector("table");
				if (table && table.parentNode) {
					table.parentNode.insertBefore(bar, table);
				} else {
					servers.insertBefore(bar, servers.firstChild);
				}
				return bar;
			};

			const placeProbeButton = () => {
				const btn = ensureProbeButton();
				if (!btn) {
					return null;
				}
				const bar = ensureProbeToolbar();
				const mobile = window.matchMedia("(max-width: 768px)").matches;
				if (mobile && bar) {
					bar.style.display = "block";
					btn.style.marginLeft = "0";
					btn.style.width = "100%";
					btn.style.minWidth = "0";
					if (btn.parentNode !== bar) {
						bar.appendChild(btn);
					}
				} else {
					if (bar) {
						bar.style.display = "none";
					}
					btn.style.marginLeft = "8px";
					btn.style.width = "";
					btn.style.minWidth = "150px";
					const headerRow = normalizeHeaderLayout();
					if (headerRow) {
						const headerCells = headerRow.querySelectorAll("th");
						const targetHeader = headerCells.length ? headerCells[headerCells.length - 1] : null;
						if (targetHeader && btn.parentNode !== targetHeader) {
							targetHeader.appendChild(btn);
						}
					}
				}
				return btn;
			};
'''


def patch(root):
    path = root / 'feeds/helloworld/luci-app-ssr-plus/luasrc/view/shadowsocksr/server_list.htm'
    text = path.read_text(encoding='utf-8')
    text = once(
        text,
        '\t\t\t\ttargetHeader.appendChild(toggleBtn);\n'
        '\t\t\t\treturn toggleBtn;\n'
        '\t\t\t};\n'
        '\n'
        '\t\t\tconst setProbeState = (running) => {\n'
        '\t\t\t\tprobing = running;\n'
        '\t\t\t\tconst btn = ensureProbeButton();\n',
        '\t\t\t\ttargetHeader.appendChild(toggleBtn);\n'
        '\t\t\t\treturn toggleBtn;\n'
        '\t\t\t};\n'
        + HELPERS +
        '\n'
        '\t\t\tconst setProbeState = (running) => {\n'
        '\t\t\t\tprobing = running;\n'
        '\t\t\t\tconst btn = placeProbeButton();\n',
    )
    text = once(
        text,
        '\t\t\tsetProbeState(false);\n'
        '\n'
        '\t\t\tensureProbeButton();\n'
        '\t\t\tif (toggleBtn) {\n'
        '\t\t\t\ttoggleBtn.onclick = function () {\n'
        '\t\t\t\t\tif (probing) {\n'
        '\t\t\t\t\t\tstopProbe();\n'
        '\t\t\t\t\t} else {\n'
        '\t\t\t\t\t\tstartProbe();\n'
        '\t\t\t\t\t}\n'
        '\t\t\t\t};\n'
        '\t\t\t}\n'
        '\t\t});\n',
        '\t\t\tsetProbeState(false);\n'
        '\n'
        '\t\t\tplaceProbeButton();\n'
        '\t\t\tif (toggleBtn) {\n'
        '\t\t\t\ttoggleBtn.onclick = function () {\n'
        '\t\t\t\t\tif (probing) {\n'
        '\t\t\t\t\t\tstopProbe();\n'
        '\t\t\t\t\t} else {\n'
        '\t\t\t\t\t\tstartProbe();\n'
        '\t\t\t\t\t}\n'
        '\t\t\t\t};\n'
        '\t\t\t}\n'
        '\t\t\twindow.addEventListener("resize", function () {\n'
        '\t\t\t\tplaceProbeButton();\n'
        '\t\t\t});\n'
        '\t\t});\n',
    )
    path.write_text(text, encoding='utf-8', newline='\n')
    print('patched', path.relative_to(root))


if __name__ == '__main__':
    patch(Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve())
