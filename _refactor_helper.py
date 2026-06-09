#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blur-main.py 重構輔助腳本：移除已提取到新模組的 class，加入 import。
行號均為 1-indexed（與編輯器顯示一致）。
"""

def main():
    src = 'D:/software/Gemini/rag-image/Blur-main.py'
    with open(src, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    total = len(lines)
    print(f"讀取完成，共 {total} 行")

    # 要移除的行範圍（1-indexed，含兩端）
    # 從後往前排序，避免行號位移
    ranges_to_remove = sorted([
        (6164, 6364),   # OnboardingDialog + TransparentDragListWidget + SettingsDialog
        (4549, 4936),   # Win32 constants + structs + event filters
        (4500, 4548),   # EmptyStateOverlay
        (4196, 4499),   # Feature widgets
        (3395, 4195),   # Sidebar widgets
        (2705, 3394),   # PreviewOverlay
        (2233, 2704),   # FloatingWidget + OCRLabel
        (1971, 2232),   # Workers
        (1268, 1970),   # ImageSearchEngine
        (628,  1267),   # SearchResultsModel + ImageDelegate + GalleryListView
        (220,  627),    # ImageItem + FunnelCardItem + CropOCRSignals + CropOCRWorker + PreviewLoader + ThumbnailLoader
        (117,  219),    # Win32 constants + TaskbarController
    ], key=lambda x: -x[0])

    # 轉換為 0-indexed 並從後往前刪除
    for start1, end1 in ranges_to_remove:
        s = start1 - 1  # 0-indexed
        e = end1        # end1 是 1-indexed 含端點，所以 0-indexed 切片上界 = end1
        print(f"  移除 L{start1}-L{end1}（{end1-start1+1} 行）")
        del lines[s:e]

    print(f"移除後剩餘 {len(lines)} 行")

    # 找到現有 import 結束的位置（找到第一個空行後的 THUMBNAIL_SIZE 那行）
    insert_pos = None
    for i, line in enumerate(lines):
        if line.strip().startswith('THUMBNAIL_SIZE'):
            insert_pos = i
            break

    if insert_pos is None:
        # fallback：找最後一個 from ... import 行
        for i in range(len(lines)-1, -1, -1):
            if lines[i].startswith('from ') or lines[i].startswith('import '):
                insert_pos = i + 1
                break

    print(f"在第 {insert_pos+1} 行插入新 import（插入前行: {lines[insert_pos].rstrip()!r}）")

    new_imports = [
        '\n',
        '# ── 已提取的模組 import ──────────────────────────────────────────────\n',
        'from core.taskbar_controller import (\n',
        '    TaskbarController, TBPF_NOPROGRESS, TBPF_INDETERMINATE,\n',
        '    TBPF_NORMAL, TBPF_ERROR, TBPF_PAUSED)\n',
        'from core.image_search_engine import ImageSearchEngine\n',
        'from core.win_event_filters import (\n',
        '    WinMaxHoverFilter, WinScanCtrlFilter)\n',
        'from core.workers import (\n',
        '    WorkerSignals, PreviewSignals, CropOCRSignals,\n',
        '    IndexerWorker, SearchWorker, OCRImportWorker, ONNXExportWorker)\n',
        'from ui.gallery_model import SearchResultsModel, GalleryListView\n',
        'from ui.preview_overlay import PreviewOverlay\n',
        'from ui.settings_dialog import SettingsDialog, OnboardingDialog\n',
        'from ui.sidebar_widget import (\n',
        '    SidebarWidget, StatsMenuWidget, FolderHoverMenu,\n',
        '    DroppableFolderButton, CollectionHoverMenu)\n',
        'from ui.widgets.empty_state import EmptyStateOverlay\n',
        'from ui.widgets.feature_widgets import (\n',
        '    TextFeatureWidget, FeatureBucketWidget, ThumbnailSignals, ThumbnailWorker)\n',
        'from ui.widgets.image_delegate import (\n',
        '    ImageItem, FunnelCardItem, ImageDelegate, PreviewLoader, ThumbnailLoader)\n',
        'from ui.widgets.ocr_widgets import (\n',
        '    CropOCRWorker, FloatingWidget, OCRLabel, CropOCRSignals)\n',
        '\n',
    ]

    lines[insert_pos:insert_pos] = new_imports

    with open(src, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    print(f"完成！最終行數: {len(lines)}")
    print("備份原始文件建議：git diff Blur-main.py 確認變更")

if __name__ == '__main__':
    main()
