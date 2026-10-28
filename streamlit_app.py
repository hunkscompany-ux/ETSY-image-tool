import streamlit as st

from core import process_files

MAX_FILES = 40  # 免费层内存有限，一次别太多

st.set_page_config(page_title="素材批量处理", layout="wide")
st.title("插画素材批量处理")
st.caption("去白底 → 裁边 → 300dpi 透明 PNG → 可选拼成整页素材页（PNG + PDF）。"
           "上传的文件会经过 Streamlit 的服务器处理，请不要上传不想外泄的素材，或把应用设为私有访问。")

with st.sidebar:
    st.header("参数")
    tol = st.slider("去白底容差", 5, 60, 28, help="边缘有白边就调大；浅色素材被吃掉就调小")
    white_thr = st.slider("白底最低亮度", 190, 250, 235, help="背景偏灰白的图调到 205 左右")
    sheet = st.checkbox("拼成整页素材页", value=True)
    page = st.selectbox("页面尺寸", ["letter", "a4"], disabled=not sheet)
    max_inch = st.slider("每个素材最长边（英寸）", 1.0, 5.0, 3.0, 0.5, disabled=not sheet,
                         help="只缩小，不放大，保证 300dpi 清晰度")
    margin_in = st.slider("页边距（英寸）", 0.0, 1.0, 0.4, 0.05, disabled=not sheet)
    gap_in = st.slider("素材间距（英寸）", 0.0, 0.5, 0.15, 0.05, disabled=not sheet)

uploads = st.file_uploader("上传图片（可多选，jpg / png / webp）",
                           type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
if uploads and len(uploads) > MAX_FILES:
    st.warning(f"一次最多处理 {MAX_FILES} 张（内存有限），已只取前 {MAX_FILES} 张。")
    uploads = uploads[:MAX_FILES]

if st.button("开始处理", type="primary", disabled=not uploads):
    with st.spinner("处理中……"):
        files = [(f.name, f.getvalue()) for f in uploads]
        st.session_state["result"] = process_files(
            files, tol=tol, white_thr=white_thr, sheet=sheet, page=page,
            max_inch=max_inch, margin_in=margin_in, gap_in=gap_in)

res = st.session_state.get("result")
if res:
    ok = sum(1 for r in res["rows"] if r.get("状态") == "已去底")
    c1, c2, c3 = st.columns(3)
    c1.metric("已处理", len(res["rows"]))
    c2.metric("已自动去底", ok)
    c3.metric("需人工处理", len(res["skipped"]))
    st.download_button("下载全部结果（zip）", data=res["zip"],
                       file_name="processed.zip", mime="application/zip", type="primary")
    if res["skipped"]:
        st.warning("以下文件背景不是白色，未去底（可能是铺满画面的设计，或背景偏灰白，可调低“白底最低亮度”重试）：\n\n"
                   + "\n".join(f"- {n}" for n in res["skipped"]))
    st.subheader("处理明细")
    st.dataframe(res["rows"], use_container_width=True)
    if res["sheets"]:
        st.subheader("整页素材页预览")
        tabs = st.tabs([f"第 {i} 页" for i in range(1, len(res["sheets"]) + 1)])
        for tab, img in zip(tabs, res["sheets"]):
            tab.image(img)
    st.subheader("单个素材预览（纸色背景，用来检查边缘）")
    cols = st.columns(6)
    for i, (name, img) in enumerate(res["pieces"]):
        cols[i % 6].image(img, caption=name[:24])
