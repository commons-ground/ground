"""公的・学術サイトの許可リストを作る。出力：claude-code-settings.json と sites.txt（このフォルダ）。
入れる基準は SKILL.md の「入れる基準」。登録資格が規則で限られているドメインだけを、ワイルドカードの効き方を確かめた形で書く。"""
import json, pathlib
PREFS = "hokkaido aomori iwate miyagi akita yamagata fukushima ibaraki tochigi gunma saitama chiba kanagawa niigata toyama ishikawa fukui yamanashi nagano gifu shizuoka aichi mie shiga kyoto osaka hyogo nara wakayama tottori shimane okayama hiroshima yamaguchi tokushima kagawa ehime kochi fukuoka saga nagasaki kumamoto oita miyazaki kagoshima okinawa".split()
SEIREI = "sapporo sendai saitama chiba yokohama kawasaki sagamihara niigata shizuoka hamamatsu nagoya kyoto osaka sakai kobe okayama hiroshima kitakyushu fukuoka kumamoto".split()
hosts = []
def both(h): hosts.extend([h, "*." + h])
# A-1 政府・自治体・大学（JPRSの規則で登録できる組織が限られている）
hosts += ["*.go.jp", "*.lg.jp", "*.ac.jp"]
# A-2 地方公共団体ドメイン名（JPRS 技術細則 2.2.2）
both("metro.tokyo.jp")
for p in PREFS:
    both(f"pref.{p}.jp")
    for kind in ("city", "town", "vill"):
        hosts += [f"{kind}.*.{p}.jp", f"*.{kind}.*.{p}.jp"]
hosts += ["city.*.tokyo.jp", "*.city.*.tokyo.jp", "town.*.tokyo.jp", "*.town.*.tokyo.jp", "vill.*.tokyo.jp", "*.vill.*.tokyo.jp"]
for c in SEIREI:
    both(f"city.{c}.jp")
# A-3 海外の政府・国際機関（登録できる組織が限られている）
hosts += ["*.gov", "*.int", "*.europa.eu"]
# B 個別に確かめた学術の基盤
hosts += ["doi.org", "api.crossref.org"]
seen = []
[seen.append(h) for h in hosts if h not in seen]
here = pathlib.Path(__file__).parent
(here / "claude-code-settings.json").write_text(json.dumps({"permissions": {"allow": [f"WebFetch(domain:{h})" for h in seen]}}, ensure_ascii=False, indent=2) + "\n")
(here / "sites.txt").write_text("\n".join(seen) + "\n")
print(len(seen))
