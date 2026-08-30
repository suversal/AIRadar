import fs from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const repoRoot = "/Users/sue/Developer/AIRadar";
const outputDir = `${repoRoot}/outputs/019f60b5-b92c-70a3-86bf-4d1f873e5ee2`;
const outputPath = `${outputDir}/AIRadar_信源清单_含补充地址_2026-07-15.xlsx`;
const previewPath = `${outputDir}/AIRadar_信源清单_预览.png`;
const supplementaryPreviewPath = `${outputDir}/AIRadar_补充地址_预览.png`;

const pythonCode = String.raw`
import json, os
from pathlib import Path
from sqlalchemy import create_engine, text

root = Path('/Users/sue/Developer/AIRadar')
for p in (root / '.env', root / 'apps/api/.env'):
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

engine = create_engine(os.environ['DATABASE_URL'])
with engine.connect() as conn:
    rows = conn.execute(text('''
        SELECT id, name, is_active, type, tier, source_role,
               can_be_main_source, affects_heat_score, fetch_interval_min,
               language, url, homepage, config_json
        FROM sources
        ORDER BY is_active DESC, tier ASC, source_role ASC, name ASC
    ''')).mappings().all()

result = []
for row in rows:
    item = dict(row)
    cfg = item.pop('config_json') or {}
    item['selection_policy'] = cfg.get('selection_policy') or cfg.get('force_selection') or ''
    result.append(item)
print(json.dumps(result, ensure_ascii=False, default=str))
`;

const raw = execFileSync(`${repoRoot}/.venv/bin/python`, ["-c", pythonCode], {
  cwd: repoRoot,
  encoding: "utf8",
});
const sources = JSON.parse(raw);

if (sources.length !== 44) {
  throw new Error(`Expected 44 sources, received ${sources.length}`);
}

const roleLabels = {
  authority: "authority（权威）",
  context: "context（媒体/背景）",
  signal: "signal（线索）",
  aggregator: "aggregator（聚合）",
};

const headers = [
  "序号",
  "Source ID",
  "信源名称",
  "状态",
  "等级",
  "角色",
  "抓取类型",
  "语言",
  "可作主来源",
  "影响热度",
  "配置间隔（分钟）",
  "选取策略",
  "主页",
  "抓取地址",
];

const rows = sources.map((source, index) => [
  index + 1,
  source.id,
  source.name,
  source.is_active ? "启用" : "停用",
  source.tier,
  roleLabels[source.source_role] ?? source.source_role,
  source.type,
  source.language,
  source.can_be_main_source ? "是" : "否",
  source.affects_heat_score ? "是" : "否",
  Number(source.fetch_interval_min),
  source.selection_policy,
  source.homepage ?? "",
  source.url,
]);

const supplementaryUrls = [
  { platform: "OpenAI", url: "https://openai.com/news/rss.xml", type: "RSS" },
  { platform: "Google AI", url: "https://blog.google/innovation-and-ai/technology/ai/rss/", type: "RSS" },
  { platform: "Google Gemini", url: "https://blog.google/products-and-platforms/products/gemini/rss/", type: "RSS" },
  { platform: "Google DeepMind", url: "https://deepmind.google/blog/rss.xml", type: "RSS" },
  { platform: "GitHub Changelog", url: "https://github.blog/changelog/feed/", type: "RSS", note: "GitHub 官方更新日志 RSS" },
  { platform: "GitHub Blog", url: "https://github.blog/feed/", type: "RSS", note: "GitHub 全站内容 RSS" },
  { platform: "GitHub AI & ML", url: "https://github.blog/ai-and-ml/feed/", type: "RSS" },
  { platform: "GitHub Engineering", url: "https://github.blog/engineering/feed/", type: "RSS", note: "GitHub Engineering RSS" },
  { platform: "NVIDIA Developer", url: "https://developer.nvidia.com/blog/feed/", type: "RSS" },
  { platform: "Microsoft Blogs", url: "https://blogs.microsoft.com/feed/", type: "RSS", note: "Microsoft 官方博客综合 RSS" },
  { platform: "Hugging Face Blog", url: "https://huggingface.co/blog/feed.xml", type: "RSS" },
  { platform: "Hugging Face Papers", url: "https://huggingface.co/api/daily_papers", type: "API" },
  { platform: "arXiv cs.AI", url: "https://rss.arxiv.org/rss/cs.AI", type: "RSS", note: "与 arxiv_ai 主题重叠，但抓取地址不同" },
  { platform: "arXiv cs.CL", url: "https://rss.arxiv.org/rss/cs.CL", type: "RSS", note: "与 arxiv_ai 主题重叠，但抓取地址不同" },
  { platform: "Hacker News Top", url: "https://hacker-news.firebaseio.com/v0/topstories.json", type: "API", note: "现有 hacker_news 使用 Algolia AI 查询，此接口不重复" },
  { platform: "Hacker News New", url: "https://hacker-news.firebaseio.com/v0/newstories.json", type: "API", note: "现有 hacker_news 使用 Algolia AI 查询，此接口不重复" },
  { platform: "Hacker News Best", url: "https://hacker-news.firebaseio.com/v0/beststories.json", type: "API", note: "现有 hacker_news 使用 Algolia AI 查询，此接口不重复" },
  { platform: "Hacker News Item", url: "https://hacker-news.firebaseio.com/v0/item/{id}.json", type: "API 模板", note: "详情接口模板；需用文章 ID 替换 {id}" },
];

const existingByUrl = new Map(sources.map((source) => [source.url, source]));
const supplementaryRows = supplementaryUrls.map((item, index) => {
  const match = existingByUrl.get(item.url);
  return [
    index + 1,
    item.platform,
    item.url,
    item.type,
    match ? "重复（已在数据库）" : "新增地址",
    match?.id ?? "",
    match?.name ?? "",
    match ? "与数据库抓取地址完全相同" : (item.note ?? "数据库中暂无相同抓取地址"),
  ];
});
const duplicateCount = supplementaryRows.filter((row) => row[4] === "重复（已在数据库）").length;

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("信源清单");
sheet.showGridLines = false;
sheet.getRange("A1:N74").format = {
  fill: "#FFFFFF",
  font: { color: "#243746" },
};

sheet.getRange("A1:N1").merge();
sheet.getRange("A1").values = [["AI·RADAR 数据库信源清单"]];
sheet.getRange("A1:N1").format = {
  fill: "#17324D",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
sheet.getRange("A1:N1").format.rowHeight = 34;

sheet.getRange("A2:B3").values = [
  ["信源总数", null],
  ["启用信源", null],
];
sheet.getRange("D2:E3").values = [
  ["停用信源", null],
  ["生成日期", "2026-07-15"],
];
sheet.getRange("B2").formulas = [["=COUNTA(A6:A49)"]];
sheet.getRange("B3").formulas = [["=COUNTIF(D6:D49,\"启用\")"]];
sheet.getRange("E2").formulas = [["=COUNTIF(D6:D49,\"停用\")"]];

for (const rangeAddress of ["A2:B3", "D2:E3"]) {
  sheet.getRange(rangeAddress).format = {
    fill: "#EAF2F8",
    borders: { preset: "outside", style: "thin", color: "#B7C9D6" },
    verticalAlignment: "center",
  };
}
sheet.getRange("A2:A3").format.font = { bold: true, color: "#35546B" };
sheet.getRange("D2:D3").format.font = { bold: true, color: "#35546B" };
sheet.getRange("B2:B3").format.font = { bold: true, color: "#17324D", size: 12 };
sheet.getRange("E2:E3").format.font = { bold: true, color: "#17324D", size: 12 };

sheet.getRange("G2:N3").merge();
sheet.getRange("G2").values = [[
  "说明：抓取间隔为数据库配置值；当前统一刷新任务尚未按该字段对单个信源独立调度。",
]];
sheet.getRange("G2:N3").format = {
  fill: "#FFF8E1",
  font: { color: "#7A5B00", italic: true },
  wrapText: true,
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#E5C768" },
};

sheet.getRange("A5:N5").values = [headers];
sheet.getRange("A6:N49").values = rows;

const table = sheet.tables.add("A5:N49", true, "SourceInventoryTable");
table.style = "TableStyleMedium2";
table.showHeaders = true;
table.showFilterButton = true;
table.showBandedRows = true;

sheet.getRange("A5:N5").format = {
  fill: "#1F6F78",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
sheet.getRange("A5:N5").format.rowHeight = 30;
sheet.getRange("A6:N49").format.verticalAlignment = "center";
sheet.getRange("A6:A49").format.horizontalAlignment = "center";
sheet.getRange("D6:L49").format.horizontalAlignment = "center";
sheet.getRange("K6:K49").format.numberFormat = "0";
sheet.getRange("M6:N49").format.font = { color: "#245B78", size: 9 };

sheet.getRange("D6:D49").conditionalFormats.add("containsText", {
  text: "启用",
  format: { fill: "#E8F5E9", font: { color: "#1B5E20", bold: true } },
});
sheet.getRange("D6:D49").conditionalFormats.add("containsText", {
  text: "停用",
  format: { fill: "#FDECEC", font: { color: "#A61B1B", bold: true } },
});
sheet.getRange("E6:E49").format = {
  fill: "#EAF2F8",
  font: { color: "#17324D", bold: true },
  horizontalAlignment: "center",
};

const widths = {
  A: 7,
  B: 24,
  C: 30,
  D: 10,
  E: 9,
  F: 23,
  G: 17,
  H: 9,
  I: 13,
  J: 11,
  K: 18,
  L: 20,
  M: 44,
  N: 64,
};
for (const [column, width] of Object.entries(widths)) {
  sheet.getRange(`${column}:${column}`).format.columnWidth = width;
}
sheet.getRange("A6:N49").format.rowHeight = 22;
sheet.freezePanes.freezeRows(5);
sheet.freezePanes.freezeColumns(3);

sheet.getRange("A52:N52").merge();
sheet.getRange("A52").values = [["补充信源地址及重复检查"]];
sheet.getRange("A52:N52").format = {
  fill: "#17324D",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
sheet.getRange("A52:N52").format.rowHeight = 34;

sheet.getRange("A53:B54").values = [
  ["补充地址总数", null],
  ["现有重复", null],
];
sheet.getRange("D53:E54").values = [
  ["新增地址", null],
  ["核对日期", "2026-07-15"],
];
sheet.getRange("B53").formulas = [["=COUNTA(A57:A74)"]];
sheet.getRange("B54").formulas = [["=COUNTIF(E57:E74,\"重复（已在数据库）\")"]];
sheet.getRange("E53").formulas = [["=COUNTIF(E57:E74,\"新增地址\")"]];
for (const rangeAddress of ["A53:B54", "D53:E54"]) {
  sheet.getRange(rangeAddress).format = {
    fill: "#EAF2F8",
    borders: { preset: "outside", style: "thin", color: "#B7C9D6" },
    verticalAlignment: "center",
  };
}
sheet.getRange("A53:A54").format.font = { bold: true, color: "#35546B" };
sheet.getRange("D53:D54").format.font = { bold: true, color: "#35546B" };
sheet.getRange("B53:B54").format.font = { bold: true, color: "#17324D", size: 12 };
sheet.getRange("E53:E54").format.font = { bold: true, color: "#17324D", size: 12 };
sheet.getRange("G53:N54").merge();
sheet.getRange("G53").values = [[
  "重复判定口径：与 sources.url 完全一致。相同平台但不同接口或不同 Feed 地址标记为新增，并在备注中说明。",
]];
sheet.getRange("G53:N54").format = {
  fill: "#FFF8E1",
  font: { color: "#7A5B00", italic: true },
  wrapText: true,
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#E5C768" },
};

for (const rangeAddress of ["B56:C56", "E56:F56", "G56:H56", "I56:J56", "K56:M56"]) {
  sheet.getRange(rangeAddress).merge();
}
sheet.getRange("A56").values = [["序号"]];
sheet.getRange("B56").values = [["平台/内容"]];
sheet.getRange("D56").values = [["类型"]];
sheet.getRange("E56").values = [["判定"]];
sheet.getRange("G56").values = [["对应 Source ID"]];
sheet.getRange("I56").values = [["对应信源"]];
sheet.getRange("K56").values = [["备注"]];
sheet.getRange("N56").values = [["地址"]];
sheet.getRange("A56:N56").format = {
  fill: "#1F6F78",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
sheet.getRange("A56:N56").format.rowHeight = 30;

for (let index = 0; index < supplementaryRows.length; index += 1) {
  const rowNumber = 57 + index;
  const [number, platform, url, type, decision, sourceId, sourceName, note] = supplementaryRows[index];
  for (const rangeAddress of [
    `B${rowNumber}:C${rowNumber}`,
    `E${rowNumber}:F${rowNumber}`,
    `G${rowNumber}:H${rowNumber}`,
    `I${rowNumber}:J${rowNumber}`,
    `K${rowNumber}:M${rowNumber}`,
  ]) {
    sheet.getRange(rangeAddress).merge();
  }
  sheet.getRange(`A${rowNumber}`).values = [[number]];
  sheet.getRange(`B${rowNumber}`).values = [[platform]];
  sheet.getRange(`D${rowNumber}`).values = [[type]];
  sheet.getRange(`E${rowNumber}`).values = [[decision]];
  sheet.getRange(`G${rowNumber}`).values = [[sourceId]];
  sheet.getRange(`I${rowNumber}`).values = [[sourceName]];
  sheet.getRange(`K${rowNumber}`).values = [[note]];
  sheet.getRange(`N${rowNumber}`).values = [[url]];
  sheet.getRange(`A${rowNumber}:N${rowNumber}`).format = {
    fill: index % 2 === 0 ? "#D9F0FA" : "#FFFFFF",
    borders: {
      bottom: { style: "thin", color: "#8ED3F4" },
    },
    verticalAlignment: "center",
  };
  sheet.getRange(`E${rowNumber}:F${rowNumber}`).format = {
    fill: decision.startsWith("重复") ? "#FFF3CD" : "#E8F5E9",
    font: {
      color: decision.startsWith("重复") ? "#7A5200" : "#1B5E20",
      bold: true,
    },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
}
sheet.getRange("A57:N74").format.verticalAlignment = "center";
sheet.getRange("A57:A74").format.horizontalAlignment = "center";
sheet.getRange("D57:D74").format.horizontalAlignment = "center";
sheet.getRange("N57:N74").format.font = { color: "#245B78", size: 9 };
sheet.getRange("A57:N74").format.rowHeight = 24;

const inspected = await workbook.inspect({
  kind: "table",
  range: "信源清单!A1:N12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 14,
  maxChars: 9000,
});
console.log(inspected.ndjson);

const supplementaryInspected = await workbook.inspect({
  kind: "table",
  range: "信源清单!A52:N74",
  include: "values,formulas",
  tableMaxRows: 23,
  tableMaxCols: 14,
  maxChars: 16000,
});
console.log(supplementaryInspected.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const preview = await workbook.render({
  sheetName: "信源清单",
  range: "A1:N49",
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const supplementaryPreview = await workbook.render({
  sheetName: "信源清单",
  range: "A52:N74",
  scale: 1.2,
  format: "png",
});
await fs.writeFile(supplementaryPreviewPath, new Uint8Array(await supplementaryPreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({
  outputPath,
  previewPath,
  supplementaryPreviewPath,
  sourceCount: sources.length,
  supplementaryCount: supplementaryRows.length,
  duplicateCount,
  newCount: supplementaryRows.length - duplicateCount,
}));
