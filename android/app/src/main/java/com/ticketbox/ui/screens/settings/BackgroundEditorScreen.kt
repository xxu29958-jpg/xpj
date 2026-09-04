package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.DialogWindowProvider
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.appearance.background.BackgroundPreviewStage
import com.ticketbox.ui.appearance.background.BackgroundTransformGeometry
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.appearance.background.rememberBackgroundImage
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.theme.configureTicketboxSystemBars
import com.ticketbox.viewmodel.BackgroundEditorState

/**
 * 独立的全窗口编辑面，不继承设置页或安全提示横幅扣减后的内容高度。
 * 舞台和全局背景使用相同画布，系统栏 inset 只作用于浮动控件。
 * 草稿、保存和取消仍由 AppearanceViewModel 拥有；没有第二套编辑状态。
 */
@Composable
internal fun BackgroundEditorScreen(
    editor: BackgroundEditorState,
    currentSkin: AppSkin,
    actions: BackgroundEditorActions,
) {
    Dialog(
        onDismissRequest = actions.onCancel,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            decorFitsSystemWindows = false,
            dismissOnBackPress = !editor.saving,
            dismissOnClickOutside = false,
        ),
    ) {
        BackgroundEditorContent(editor, currentSkin, actions)
    }
}

@Composable
private fun BackgroundEditorContent(
    editor: BackgroundEditorState,
    currentSkin: AppSkin,
    actions: BackgroundEditorActions,
) {
    val view = LocalView.current
    SideEffect {
        configureTicketboxSystemBars((view.parent as DialogWindowProvider).window, view, currentSkin)
    }
    val draft = editor.settings
    var previewRole by remember { mutableStateOf(SurfaceRole.Ledger) }
    Box(modifier = Modifier.fillMaxSize()) {
        BackgroundEditorStage(
            draft = draft,
            skin = currentSkin,
            role = previewRole,
            gesturesEnabled = !editor.saving,
            onTransformChange = { transform ->
                actions.onDraftChange(draft.copy(transform = transform))
            },
        )
        BackgroundEditorTopBar(
            onBack = actions.onCancel,
            enabled = !editor.saving,
            modifier = Modifier.align(Alignment.TopStart),
        )
        BackgroundEditorStageCaption(
            modifier = Modifier.align(Alignment.TopCenter),
        )
        BackgroundEditorControlPanel(
            editor = editor,
            previewRole = previewRole,
            onRoleSelect = { previewRole = it },
            actions = actions,
            modifier = Modifier.align(Alignment.BottomCenter),
        )
    }
}

internal data class BackgroundEditorActions(
    val onDraftChange: (BackgroundSettings) -> Unit,
    val onCancel: () -> Unit,
    val onApply: () -> Unit,
)

/** 编辑器预览的页面角色抽样：覆盖用户最常看背景的五个面，Today/Auth 由真实页面验收。 */
private val backgroundEditorPreviewRoles = listOf(
    SurfaceRole.Pending,
    SurfaceRole.Ledger,
    SurfaceRole.Stats,
    SurfaceRole.Edit,
    SurfaceRole.Settings,
)

/**
 * 全屏预览舞台：真实三层渲染（[BackgroundPreviewStage]）+ 拖捏手势。
 * 与 renderer 同一 geometry 单源；视差 1.01–1.05 的额外缩放在手势闭环
 * （拖到边界即收敛）下不可感知，不重复计入。
 */
@Composable
private fun BackgroundEditorStage(
    draft: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
    gesturesEnabled: Boolean,
    onTransformChange: (BackgroundTransform) -> Unit,
) {
    val customPath = draft.customImagePath
        ?.takeIf { draft.source == BackgroundSource.CustomImage }
    val bitmap = rememberBackgroundImage(customPath)
    val imageSize = bitmap?.let { IntSize(it.width, it.height) } ?: IntSize.Zero
    var viewportSize by remember { mutableStateOf(IntSize.Zero) }
    val currentDraft by rememberUpdatedState(draft)
    val currentOnTransformChange by rememberUpdatedState(onTransformChange)
    val canGesture = gesturesEnabled && imageSize != IntSize.Zero
    Box(
        modifier = Modifier
            .fillMaxSize()
            .testTag("background-editor-viewport")
            .onSizeChanged { viewportSize = it }
            .then(
                if (canGesture) {
                    Modifier.pointerInput(imageSize) {
                        detectTransformGestures { _, pan, zoom, _ ->
                            val zoomed = BackgroundTransformGeometry.zoomed(
                                currentDraft.transform,
                                zoom,
                            )
                            val panned = BackgroundTransformGeometry.panned(
                                current = zoomed,
                                panPx = pan,
                                viewport = viewportSize,
                                image = imageSize,
                            )
                            if (panned != currentDraft.transform) {
                                currentOnTransformChange(panned)
                            }
                        }
                    }
                } else {
                    Modifier
                },
            ),
    ) {
        BackgroundPreviewStage(
            settings = draft,
            skin = skin,
            role = role,
            modifier = Modifier.fillMaxSize(),
        )
    }
}

/** 顶部浮动栏：返回（= 取消，VM 丢弃 draft 与候选文件）+ 标题，半透明 chip 保可读。 */
@Composable
private fun BackgroundEditorTopBar(
    onBack: () -> Unit,
    enabled: Boolean,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .statusBarsPadding()
            .padding(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(
            onClick = onBack,
            enabled = enabled,
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.heavy)),
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.background_editor_cancel_button),
            )
        }
        Text(
            text = stringResource(R.string.background_editor_page_title),
            modifier = Modifier
                .padding(start = AppSpacing.smallGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.heavy))
                .padding(
                    horizontal = AppSpacing.compactGap,
                    vertical = AppSpacing.smallGap,
                ),
            style = MaterialTheme.typography.titleMedium,
        )
    }
}

@Composable
private fun BackgroundEditorStageCaption(
    modifier: Modifier = Modifier,
) {
    Text(
        text = stringResource(R.string.background_editor_stage_caption),
        modifier = modifier
            .statusBarsPadding()
            // 顶栏高度 = 48dp 触控 + 上下 smallGap；caption 贴在其下，不与标题重叠。
            .padding(top = AppSpacing.controlMinHeight + AppSpacing.smallGap * 2)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.heavy))
            .padding(
                horizontal = AppSpacing.compactGap,
                vertical = AppSpacing.tinyGap,
            ),
        style = MaterialTheme.typography.labelSmall,
    )
}

/**
 * 底部控制面板：角色抽样 / 构图 / 沉浸 / 取消应用。近实心 surface 保证控件
 * 自身可读（控件不是被预览对象）；面板可滚动，小屏不挤掉按钮。
 */
@Composable
private fun BackgroundEditorControlPanel(
    editor: BackgroundEditorState,
    previewRole: SurfaceRole,
    onRoleSelect: (SurfaceRole) -> Unit,
    actions: BackgroundEditorActions,
    modifier: Modifier = Modifier,
) {
    val draft = editor.settings
    val maxPanelHeight = LocalConfiguration.current.screenHeightDp.dp * 0.56f
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(topStart = AppRadius.large, topEnd = AppRadius.large),
        color = MaterialTheme.colorScheme.surface.copy(alpha = AppAlpha.opaque),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = maxPanelHeight)
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(AppSpacing.contentGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            AppStatusBanner(message = editor.message, tone = MessageTone.Danger)
            BackgroundEditorPanelLabel(text = stringResource(R.string.background_editor_section_preview_role))
            BackgroundEditorRolePicker(previewRole, onRoleSelect)
            if (draft.source == BackgroundSource.CustomImage) {
                BackgroundEditorPanelLabel(text = stringResource(R.string.background_editor_section_composition))
                BackgroundEditorCompositionControls(
                    transform = draft.transform,
                    enabled = !editor.saving,
                    onTransformChange = { transform ->
                        actions.onDraftChange(draft.copy(transform = transform))
                    },
                )
            }
            BackgroundEditorPanelLabel(text = stringResource(R.string.appearance_section_immersion_title))
            ImmersionModePicker(
                selected = draft.immersionMode,
                onSelect = { mode -> actions.onDraftChange(draft.copy(immersionMode = mode)) },
            )
            Text(
                text = stringResource(R.string.background_editor_scope_note),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            BackgroundEditorFooter(editor.saving, actions)
        }
    }
}

@Composable
private fun BackgroundEditorPanelLabel(
    text: String,
) {
    Text(
        text = text,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.labelLarge,
    )
}

@Composable
private fun BackgroundEditorRolePicker(
    previewRole: SurfaceRole,
    onRoleSelect: (SurfaceRole) -> Unit,
) {
    AppCompactChips {
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            backgroundEditorPreviewRoles.forEach { role ->
                AppFilterChip(
                    label = stringResource(backgroundEditorRoleNameRes(role)),
                    selected = previewRole == role,
                    onClick = { onRoleSelect(role) },
                )
            }
        }
    }
}

@Composable
private fun BackgroundEditorFooter(
    saving: Boolean,
    actions: BackgroundEditorActions,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        AppSecondaryButton(
            text = stringResource(R.string.background_editor_cancel_button),
            modifier = Modifier.weight(1f),
            enabled = !saving,
            onClick = actions.onCancel,
        )
        AppPrimaryButton(
            text = stringResource(
                if (saving) {
                    R.string.background_editor_applying
                } else {
                    R.string.background_editor_apply_button
                },
            ),
            icon = Icons.Filled.Check,
            modifier = Modifier.weight(1f),
            enabled = !saving,
            onClick = actions.onApply,
        )
    }
}
