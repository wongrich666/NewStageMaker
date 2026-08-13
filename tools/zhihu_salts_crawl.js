const { chromium } = require("playwright");

// 抓取知乎盐选每日文章（榜单 / 今日必读 / 大家在看）
// 用法：
//   node tools/zhihu_salts_crawl.js                          # 抓列表（无需登录）
//   ZHIHU_COOKIE="xxx=yyy; aaa=bbb" node tools/zhihu_salts_crawl.js --json
// 注意：盐选正文属于付费 VIP 内容，仅限你自己已订阅的内容使用，请勿公开分发。

const args = process.argv.slice(2);
const wantJson = args.includes("--json");

async function collectCards(page) {
  return page.evaluate(() => {
    const out = [];
    const seen = new Set();
    const anchors = Array.from(
      document.querySelectorAll("a[href*='/salt/'], a[href*='/p/']"),
    );
    for (const a of anchors) {
      const href = a.getAttribute("href") || "";
      const card = a.closest("div, section, article");
      const text = (card && card.innerText) || a.innerText || "";
      const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
      const title = lines.find((l) => l.length >= 4 && l.length <= 40);
      if (!title || seen.has(href)) continue;
      seen.add(href);
      const url = href.startsWith("http") ? href : `https://www.zhihu.com${href}`;
      const likes = lines.find((l) => /万?\s?赞/.test(l)) || "";
      const tags = lines.filter((l) => l.length <= 20 && (l.includes("·") || l.includes("言情") || l.includes("悬疑") || l.includes("脑洞")));
      out.push({
        title,
        intro: lines.filter((l) => l.length > 20).slice(0, 2).join(" ").slice(0, 120),
        url,
        likes,
        tags: tags.slice(0, 3),
      });
    }
    return out;
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    locale: "zh-CN",
  });
  if (process.env.ZHIHU_COOKIE) {
    await context.addCookies(
      process.env.ZHIHU_COOKIE.split(";").map((kv) => {
        const [name, value] = kv.trim().split("=");
        return { name, value, url: "https://www.zhihu.com" };
      }),
    );
  }
  const page = await context.newPage();
  await page.goto("https://www.zhihu.com/fiore/h5/vip-web", {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await page.waitForTimeout(4000);

  const items = await collectCards(page);

  const sections = await page.evaluate(() =>
    Array.from(document.querySelectorAll("h1,h2,h3"))
      .map((el) => (el.innerText || "").trim())
      .filter(Boolean)
      .slice(0, 20),
  );

  if (wantJson) {
    console.log(JSON.stringify({ url: page.url(), sections, items }, null, 2));
  } else {
    console.log(`页面板块：${sections.join(" / ")}`);
    console.log(`共抓到 ${items.length} 条候选，前 15 条：`);
    items.slice(0, 15).forEach((it, i) => {
      console.log(`\n[${i + 1}] ${it.title}`);
      console.log(`    简介：${it.intro}`);
      console.log(`    ${it.likes}    ${it.tags.length ? `[${it.tags.join("][")}]` : ""}`);
      console.log(`    ${it.url}`);
    });
  }

  await browser.close();
})();