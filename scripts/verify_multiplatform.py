"""Opt-in adapter smoke check using local pages and a temporary browser profile."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from boss_spider import PlatformAccessStopped
from platform_browser import BrowserJobPlatform
from platform_job_parser import parse_job_cards, parse_job_detail


CARD = """
<div class="jobDetailBox">
  <a href="https://www.liepin.com/job/local123.shtml">
    <div><div class="jobTitleBox"><div title="Python developer">Python developer</div>
      <div><span>City</span></div></div><span>15-30k</span></div>
  </a><span class="companyName">Fixture Co</span>
</div>
"""


class LocalPage(BaseHTTPRequestHandler):
    def do_GET(self):
        title = "Security Verification" if self.path == "/security" else "Adapter fixture"
        alert = '<div role="alert">\u64cd\u4f5c\u9891\u7e41</div>' if self.path == "/limited" else ""
        modern = """
        <div class="job-list-panel"><div class="job-card">
          <div class="job-card__title-clamp"><span class="vue-clamp__text">Python developer</span></div>
          <div class="job-card__company-name">Fixture Co</div>
          <div class="job-card__salary">15-30k</div><div class="job-card__location">City-District</div>
        </div></div><script>
          document.querySelector('.job-card').__vue__ = {$props:{job:{number:'fixture123',
            name:'Python developer', companyName:'Fixture Co', salary60:'15-30k', workCity:'City',
            positionUrl:'https://www.zhaopin.com/jobdetail/fixture123.htm'}}};
          const panel = document.querySelector('.job-list-panel');
          panel.__vue__ = {$props:{hasMore:true}};
          const last = panel.lastElementChild;
          last.scrollIntoView = () => {
            if (!panel.__vue__.$props.hasMore) return;
            const next = last.cloneNode(true);
            next.__vue__ = {$props:{job:{...last.__vue__.$props.job, number:'fixture456',
              positionUrl:'https://www.zhaopin.com/jobdetail/fixture456.htm'}}};
            panel.append(next);
            panel.__vue__.$props.hasMore = false;
          };
        </script>
        """ if self.path == "/modern" else CARD
        content = f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
        <div class="header-quick-menu-username">Fixture Account</div>
        {modern}<dd data-selector="job-intro-content">Build Python services.</dd>{alert}
        <section class="job-apply-container"><button onclick="this.textContent='\u5df2\u6295\u9012'">
        \u7acb\u5373\u6295\u9012</button></section>""".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_args):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalPage)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    checks = {}
    try:
        with tempfile.TemporaryDirectory(prefix="autodeliver-multiplatform-") as profile:
            adapter = BrowserJobPlatform.__new__(BrowserJobPlatform)
            adapter.platform = "liepin"
            adapter.label = "Fixture platform"
            adapter.profile = profile
            adapter.headless = True
            adapter.stop_reason = ""
            adapter.config = {"job_delay": (0, 0)}
            adapter._last_navigation_at = 0
            adapter.page = adapter._open_browser()
            adapter._main_page = adapter.page
            adapter._detail_page = None
            try:
                adapter.page.get(base_url)
                assert adapter.logged_in()
                checks["login_identity"] = True
                adapter.page.run_js("""
                    document.querySelector('.header-quick-menu-username').className = 'user-name';
                    const resume = document.createElement('a');
                    resume.textContent = '\u6211\u7684\u7b80\u5386';
                    document.body.append(resume);
                """)
                assert not adapter.logged_in()
                checks["public_identity_is_not_login"] = True
                cards = parse_job_cards("liepin", adapter.page.html)
                assert len(cards) == 1 and cards[0]["salaryDesc"] == "15-30k"
                assert cards[0]["encryptJobId"] == "liepin:job:local123"
                checks["rendered_list"] = True
                assert parse_job_detail("liepin", adapter.page.html)["desc"] == "Build Python services."
                checks["rendered_detail"] = True
                assert not adapter.already_applied()
                button = next(element for element in adapter._job_buttons()
                              if adapter._button_text(element) == "\u7acb\u5373\u6295\u9012")
                button.click()
                assert adapter.page.wait.ele_displayed('text:\u5df2\u6295\u9012', timeout=3)
                assert adapter.already_applied()
                checks["explicit_receipt"] = True
                adapter.page.get(base_url + "/modern")
                adapter.platform = "zhilian"
                modern_jobs = adapter._read_jobs()
                assert len(modern_jobs) == 1 and modern_jobs[0]["encryptJobId"] == "zhilian:fixture123"
                checks["zhilian_bound_card"] = True
                seen = {job["encryptJobId"] for job in modern_jobs}
                list_page = adapter.page
                adapter._activate_detail_page()
                adapter.page.get(base_url)
                assert adapter.page.tab_id != list_page.tab_id
                adapter.page = list_page
                more = adapter._load_more_modern(seen)
                assert [job["encryptJobId"] for job in more] == ["zhilian:fixture456"]
                assert seen == {"zhilian:fixture123", "zhilian:fixture456"}
                assert adapter._load_more_modern(seen) == []
                checks["zhilian_scroll_after_detail"] = True
                for route in ("/security", "/limited"):
                    adapter.stop_reason = ""
                    adapter.page.get(base_url + route)
                    try:
                        adapter.check_page()
                    except PlatformAccessStopped:
                        checks[route] = True
                    else:
                        raise AssertionError(f"Restriction missed: {route}")
                print(json.dumps(checks, indent=2))
            finally:
                adapter.page.quit(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
