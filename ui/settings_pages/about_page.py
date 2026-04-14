"""About & Help settings page."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame


class AboutPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        trans = ctx["translator"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(trans.t("about_page", "page_title", "ℹ️ 關於與說明 (Help & About)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("PageHLine")
        layout.addWidget(line)

        layout.addWidget(QLabel("<h2>EyeSeeMore</h2>"))

        version_info = QLabel(trans.t(
            "about_page", "version_lbl",
            "<b>版本號：</b> V0.5.0-alpha<br><b>建置日期：</b> 2026-03-18"
        ))
        layout.addWidget(version_info)

        tech_text = (
            trans.t("about_page", "tech_title",
                    "<h3>技術致敬 (Core Technologies)</h3><p>本軟體由以下優秀的開源生態系驅動：</p>") +
            "<ul>" +
            trans.t("about_page", "tech_ui",  "<li><b>介面開發：</b> Python &amp; PyQt6</li>") +
            trans.t("about_page", "tech_ai",  "<li><b>AI 推理引擎：</b> ONNX Runtime</li>") +
            trans.t("about_page", "tech_ocr", "<li><b>文字辨識 (OCR)：</b> ONNX-OCR</li>") +
            trans.t("about_page", "tech_img", "<li><b>影像與資料處理：</b> OpenCV, Pillow (PIL), NumPy</li>") +
            trans.t("about_page", "tech_db",  "<li><b>資料存儲：</b> SQLite3</li>") +
            trans.t("about_page", "tech_perf","<li><b>系統監控：</b> psutil (效能優化)</li>") +
            "</ul>"
        )
        tech_label = QLabel(tech_text)
        layout.addWidget(tech_label)

        link_color = ctx["theme_manager"].current_colors.get("text_link", "#00aaff")
        link_html = (
            f'<a href="https://github.com/Magnesiumnuclear/EyeSeeMore" '
            f'style="color: {link_color}; text-decoration: none;">'
            f'🌐 專案 GitHub 主頁 (回報問題與建議)</a>'
        )
        link_label = QLabel(trans.t("about_page", "github_link", link_html))
        link_label.setOpenExternalLinks(True)
        layout.addWidget(link_label)

        copyright_label = QLabel(trans.t(
            "about_page", "copyright",
            "<br><small>© 2026 HO99 Licensed under GPL v3.</small>"
        ))
        layout.addWidget(copyright_label)

        layout.addStretch(1)
