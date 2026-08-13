import { ImageResponse } from "next/og";

// Next 的文件约定：本文件的产物会自动挂到 og:image 和 twitter:image 上。
export const alt = "AI·RADAR — AI intelligence radar for creators and developers";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// 注意：next/og 内置字体只覆盖拉丁字符，写中文会渲染成豆腐块。
// 要放中文得自己加载 CJK 字体文件（体积很大），所以卡片上只用品牌名和英文副标题。
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 96px",
          background: "#1f1e1d",
          // 右上角一抹品牌橙的辉光，避免整张图太平
          backgroundImage:
            "radial-gradient(circle at 88% 12%, rgba(217,119,87,0.28) 0%, rgba(31,30,29,0) 55%)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          <svg width="104" height="104" viewBox="0 0 64 64">
            <rect width="64" height="64" rx="15" fill="#1f1e1d" />
            <circle cx="32" cy="31" r="21" fill="none" stroke="#f0eee6" strokeWidth="3" />
            <path d="M32 31V10a21 21 0 0 1 17 8.7Z" fill="#d97757" />
            <path
              d="M32 17a14 14 0 0 0-11.8 21.5"
              fill="none"
              stroke="#f0eee6"
              strokeLinecap="round"
              strokeWidth="2"
              opacity=".72"
            />
            <path
              d="M18.5 48 29.6 23.5a2.6 2.6 0 0 1 4.8 0L45.5 48"
              fill="none"
              stroke="#f0eee6"
              strokeLinecap="square"
              strokeLinejoin="round"
              strokeWidth="5.5"
            />
            <circle cx="32" cy="38.5" r="3.2" fill="#d97757" />
          </svg>
          <div
            style={{
              display: "flex",
              fontSize: 86,
              fontWeight: 700,
              color: "#f0eee6",
              letterSpacing: -1,
            }}
          >
            AI·RADAR
          </div>
        </div>

        <div
          style={{
            display: "flex",
            marginTop: 36,
            fontSize: 38,
            color: "#c9c4b8",
            lineHeight: 1.35,
          }}
        >
          AI intelligence radar for creators and developers
        </div>

        <div
          style={{
            display: "flex",
            marginTop: 22,
            fontSize: 27,
            color: "#8f8a80",
          }}
        >
          Scored, clustered and deduplicated by AI — one curated digest a day.
        </div>

        <div
          style={{
            display: "flex",
            marginTop: 52,
            alignItems: "center",
            gap: 14,
          }}
        >
          <div
            style={{
              display: "flex",
              width: 12,
              height: 12,
              borderRadius: 6,
              background: "#d97757",
            }}
          />
          <div style={{ display: "flex", fontSize: 25, color: "#d97757", letterSpacing: 1 }}>
            radar.suversal.com
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
