package com.ticketbox.ui.mascot

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin

internal data class V4Pose(
    val offsetX: Float = 0f,
    val offsetY: Float = 0f,
    val rotation: Float = 0f,
    val scaleX: Float = 1f,
    val scaleY: Float = 1f,
    val shadowScale: Float = 1f,
    val shadowAlpha: Float = 0.12f,
    val footLift: Float = 0f,
)

internal data class V4ArmPose(
    val leftAngle: Float,
    val rightAngle: Float,
    val leftLift: Float,
    val rightLift: Float,
    val stretchY: Float = 1f,
)

internal data class V4ReceiptMotion(
    val offsetY: Float = 0f,
    val rotation: Float = 0f,
)

internal fun v4Pose(state: MascotState, breath: Float, phase: Float): V4Pose {
    val spec = V4_POSE_SPECS[state] ?: V4PoseSpec()
    val breathe = breath - 0.5f
    val wave = v4Wave(phase)
    val bounce = v4Pulse(phase)
    return V4Pose(
        offsetX = spec.offsetX + wave * spec.offsetXWave,
        offsetY = spec.offsetY + breathe * spec.offsetYBreath + wave * spec.offsetYWave + bounce * spec.offsetYBounce,
        rotation = spec.rotation + wave * spec.rotationWave,
        scaleX = spec.scaleX + breathe * spec.scaleXBreath + bounce * spec.scaleXBounce,
        scaleY = spec.scaleY + breathe * spec.scaleYBreath + bounce * spec.scaleYBounce,
        shadowScale = spec.shadowScale + breathe * spec.shadowScaleBreath + bounce * spec.shadowScaleBounce,
        shadowAlpha = spec.shadowAlpha,
        footLift = bounce * spec.footLiftBounce,
    )
}

internal fun v4ArmPose(state: MascotState, breath: Float, phase: Float): V4ArmPose {
    val spec = V4_ARM_SPECS[state] ?: V4_ARM_SPECS.getValue(MascotState.Neutral)
    val breathe = breath - 0.5f
    val wave = v4Wave(phase)
    val bounce = v4Pulse(phase)
    return V4ArmPose(
        leftAngle = spec.leftAngle + breathe * spec.leftAngleBreath + wave * spec.leftAngleWave + bounce * spec.leftAngleBounce,
        rightAngle = spec.rightAngle + breathe * spec.rightAngleBreath + wave * spec.rightAngleWave + bounce * spec.rightAngleBounce,
        leftLift = spec.leftLift + breathe * spec.leftLiftBreath + bounce * spec.leftLiftBounce,
        rightLift = spec.rightLift + breathe * spec.rightLiftBreath + bounce * spec.rightLiftBounce,
        stretchY = spec.stretchY,
    )
}

internal fun v4ReceiptMotion(state: MascotState, phase: Float): V4ReceiptMotion {
    val spec = V4_RECEIPT_SPECS[state] ?: V4ReceiptSpec()
    val wave = v4Wave(phase)
    val bounce = v4Pulse(phase)
    return V4ReceiptMotion(
        offsetY = spec.offsetY + bounce * spec.offsetYBounce,
        rotation = spec.rotation + wave * spec.rotationWave,
    )
}

private fun v4Wave(phase: Float): Float = sin(phase * V4_TAU)

private fun v4Pulse(phase: Float): Float = 1f - abs(phase * 2f - 1f)

private const val V4_TAU = (PI * 2.0).toFloat()

private data class V4PoseSpec(
    val offsetX: Float = 0f,
    val offsetXWave: Float = 0f,
    val offsetY: Float = 0f,
    val offsetYBreath: Float = 0f,
    val offsetYWave: Float = 0f,
    val offsetYBounce: Float = 0f,
    val rotation: Float = 0f,
    val rotationWave: Float = 0f,
    val scaleX: Float = 1f,
    val scaleXBreath: Float = 0f,
    val scaleXBounce: Float = 0f,
    val scaleY: Float = 1f,
    val scaleYBreath: Float = 0f,
    val scaleYBounce: Float = 0f,
    val shadowScale: Float = 1f,
    val shadowScaleBreath: Float = 0f,
    val shadowScaleBounce: Float = 0f,
    val shadowAlpha: Float = 0.12f,
    val footLiftBounce: Float = 0f,
)

private data class V4ArmSpec(
    val leftAngle: Float = -4f,
    val leftAngleBreath: Float = 0f,
    val leftAngleWave: Float = 0f,
    val leftAngleBounce: Float = 0f,
    val rightAngle: Float = 4f,
    val rightAngleBreath: Float = 0f,
    val rightAngleWave: Float = 0f,
    val rightAngleBounce: Float = 0f,
    val leftLift: Float = 0f,
    val leftLiftBreath: Float = 0f,
    val leftLiftBounce: Float = 0f,
    val rightLift: Float = 0f,
    val rightLiftBreath: Float = 0f,
    val rightLiftBounce: Float = 0f,
    val stretchY: Float = 1f,
)

private data class V4ReceiptSpec(
    val offsetY: Float = 0f,
    val offsetYBounce: Float = 0f,
    val rotation: Float = 0f,
    val rotationWave: Float = 0f,
)

private val V4_POSE_SPECS = mapOf(
    MascotState.Neutral to V4PoseSpec(
        offsetYBreath = 2f,
        scaleXBreath = -0.008f,
        scaleYBreath = 0.012f,
        shadowScaleBreath = 0.02f,
    ),
    MascotState.Dozing to V4PoseSpec(
        offsetX = -8f,
        offsetY = 8f,
        offsetYBreath = 2f,
        rotation = -7f,
        rotationWave = 0.8f,
        scaleX = 1.025f,
        scaleY = 0.97f,
        shadowScale = 0.92f,
    ),
    MascotState.Greeting to V4PoseSpec(
        offsetY = -3f,
        offsetYBounce = -3f,
        rotation = -2f,
        rotationWave = 1.4f,
        scaleX = 1.015f,
        scaleY = 0.985f,
        shadowScale = 0.96f,
    ),
    MascotState.ClampCheer to V4PoseSpec(
        offsetY = -5f,
        offsetYBounce = -11f,
        rotationWave = 1.6f,
        scaleXBounce = 0.04f,
        scaleYBounce = -0.045f,
        shadowScale = 0.96f,
        shadowScaleBounce = -0.04f,
        footLiftBounce = 7f,
    ),
    MascotState.Celebrating to V4PoseSpec(
        offsetY = -7f,
        offsetYBounce = -4f,
        rotationWave = 1.2f,
        scaleXBounce = 0.025f,
        scaleYBounce = -0.02f,
        shadowScale = 0.94f,
        footLiftBounce = 4f,
    ),
    MascotState.Stretching to V4PoseSpec(
        offsetY = -12f,
        scaleX = 0.95f,
        scaleY = 1.08f,
        shadowScale = 0.88f,
    ),
    MascotState.Tickled to V4PoseSpec(
        offsetXWave = 5f,
        offsetY = -2f,
        offsetYBounce = 2f,
        rotationWave = 4f,
        scaleX = 1.02f,
        scaleY = 0.99f,
        shadowScale = 0.95f,
    ),
    MascotState.Shocked to V4PoseSpec(
        offsetY = 2f,
        offsetYBounce = -2f,
        rotationWave = 0.5f,
        scaleX = 0.96f,
        scaleY = 1.05f,
        shadowScale = 0.95f,
    ),
    MascotState.Juggling to V4PoseSpec(
        offsetY = -3f,
        offsetYWave = 3f,
        rotationWave = 1.5f,
        shadowScale = 0.96f,
    ),
    MascotState.Searching to V4PoseSpec(
        offsetXWave = 2f,
        rotation = -2f,
        rotationWave = 0.9f,
    ),
    MascotState.Dismissive to V4PoseSpec(
        offsetX = -4f,
        rotation = -4f,
        rotationWave = 0.6f,
        scaleX = 1.01f,
        scaleY = 0.99f,
    ),
)

private val V4_ARM_SPECS = mapOf(
    MascotState.Neutral to V4ArmSpec(
        leftAngleBreath = 2f,
        rightAngleBreath = -2f,
        leftLiftBreath = 2f,
        rightLiftBreath = 2f,
    ),
    MascotState.Dozing to V4ArmSpec(
        leftAngle = 8f,
        leftAngleWave = 1f,
        rightAngle = -8f,
        rightAngleWave = 1f,
        leftLift = 8f,
        rightLift = 8f,
    ),
    MascotState.Greeting to V4ArmSpec(
        leftAngle = -22f,
        leftAngleWave = -8f,
        leftLift = -22f,
        leftLiftBounce = -5f,
        rightAngle = 6f,
        rightAngleWave = 3f,
    ),
    MascotState.ClampCheer to V4ArmSpec(
        leftAngle = 13f,
        leftAngleWave = 4f,
        rightAngle = -13f,
        rightAngleWave = -4f,
        leftLift = -18f,
        leftLiftBounce = -4f,
        rightLift = -18f,
        rightLiftBounce = -4f,
    ),
    MascotState.Celebrating to V4ArmSpec(
        leftAngle = -18f,
        leftAngleWave = 5f,
        rightAngle = 18f,
        rightAngleWave = -5f,
        leftLift = -26f,
        leftLiftBounce = -5f,
        rightLift = -26f,
        rightLiftBounce = -5f,
    ),
    MascotState.Stretching to V4ArmSpec(
        leftAngle = -10f,
        leftAngleWave = 2f,
        rightAngle = 10f,
        rightAngleWave = -2f,
        leftLift = -34f,
        rightLift = -34f,
        stretchY = 1.08f,
    ),
    MascotState.Tickled to V4ArmSpec(
        leftAngle = 0f,
        leftAngleWave = 14f,
        rightAngle = 0f,
        rightAngleWave = -14f,
    ),
    MascotState.Shocked to V4ArmSpec(
        leftAngle = 18f,
        leftAngleBounce = -5f,
        rightAngle = -18f,
        rightAngleBounce = 5f,
        leftLift = 54f,
        rightLift = 54f,
    ),
    MascotState.Juggling to V4ArmSpec(
        leftAngle = -8f,
        leftAngleWave = 6f,
        rightAngle = 8f,
        rightAngleWave = -6f,
    ),
    MascotState.Searching to V4ArmSpec(
        leftAngle = 3f,
        leftAngleWave = 2f,
        rightAngle = -6f,
        rightAngleWave = 2f,
        rightLift = -10f,
    ),
    MascotState.Dismissive to V4ArmSpec(leftAngle = -12f, rightAngle = 11f),
)

private val V4_RECEIPT_SPECS = mapOf(
    MascotState.ClampCheer to V4ReceiptSpec(offsetY = -5f, offsetYBounce = -3f, rotationWave = 3f),
    MascotState.Celebrating to V4ReceiptSpec(offsetY = -4f, offsetYBounce = -2f, rotationWave = 2f),
    MascotState.Dozing to V4ReceiptSpec(offsetY = 4f, rotation = -3f),
    MascotState.Tickled to V4ReceiptSpec(rotationWave = 5f),
    MascotState.Searching to V4ReceiptSpec(rotation = -2f),
    MascotState.Dismissive to V4ReceiptSpec(offsetY = 2f, rotation = -3f),
)
