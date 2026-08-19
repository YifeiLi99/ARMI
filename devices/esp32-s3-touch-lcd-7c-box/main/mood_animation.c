#include "mood_animation.h"

#include <string.h>

#define FRAME_MS 80U

static int triangle(uint32_t frame, uint32_t period, int amplitude)
{
    uint32_t position = frame % period;
    uint32_t half = period / 2U;
    uint32_t value = position <= half ? position : period - position;
    return (int)(value * (uint32_t)amplitude / half);
}

static int signed_swing(uint32_t frame, uint32_t period, int amplitude)
{
    return triangle(frame, period, amplitude * 2) - amplitude;
}

static bool blink(uint32_t frame, mood_face_t face, uint8_t energy)
{
    if (face == MOOD_FACE_OFFLINE || face == MOOD_FACE_CALM) {
        return false;
    }
    uint32_t period = face == MOOD_FACE_ANXIOUS ? 31U :
                      face == MOOD_FACE_EXCITED ? 47U : 59U;
    uint32_t closed_frames = energy >= 60U ? 2U : 1U;
    return (frame + period / 2U) % period < closed_frames;
}

static void base_frame(mood_animation_frame_t *target)
{
    memset(target, 0, sizeof(*target));
    target->left_eye_width = 76;
    target->left_eye_height = 14;
    target->left_eye_x = -120;
    target->left_eye_y = -65;
    target->right_eye_width = 76;
    target->right_eye_height = 14;
    target->right_eye_x = 120;
    target->right_eye_y = -65;
    target->pupil_size = 0;
    target->pupils_visible = false;
    target->mouth_width = 72;
    target->mouth_height = 13;
    target->mouth_y = 82;
    target->cheek_y = 34;
    target->face_opacity = 255;
}

void mood_animation_frame(
    mood_face_t face,
    uint8_t energy,
    uint32_t elapsed_ms,
    mood_animation_frame_t *target
)
{
    base_frame(target);
    uint32_t frame = elapsed_ms / FRAME_MS;
    int drive = 2 + (int)energy / 20;
    int breath = triangle(frame, 50U, drive);
    target->color_lift = (uint8_t)triangle(frame, 50U, 2 + energy / 16U);
    target->face_opacity = elapsed_ms >= 320U ? 255U :
                           (uint8_t)(96U + elapsed_ms * 159U / 320U);

    if (face == MOOD_FACE_HAPPY) {
        target->left_eye_width = target->right_eye_width = 92 + breath;
        target->left_eye_height = target->right_eye_height = 34 + breath;
        target->left_eye_curve = target->right_eye_curve = -1;
        target->mouth_width = 86 + breath * 2;
        target->mouth_height = 42 + breath;
        target->mouth_y = 76 - breath;
        target->mouth_curve = 1;
        target->cheek_opacity = (uint8_t)(55 + triangle(frame, 50U, 40));
    } else if (face == MOOD_FACE_EXCITED) {
        int bounce = triangle(frame, 18U, drive * 2);
        target->left_eye_width = target->right_eye_width = 98 + bounce;
        target->left_eye_height = target->right_eye_height = 16;
        target->left_eye_rotation = 180;
        target->right_eye_rotation = -180;
        target->left_eye_y = target->right_eye_y = -65 - bounce;
        target->mouth_width = 74 + bounce * 2;
        target->mouth_height = 68 + bounce;
        target->mouth_y = 78 - bounce;
        target->mouth_curve = 2;
        target->cheek_opacity = (uint8_t)(70 + triangle(frame, 18U, 50));
        target->color_lift = (uint8_t)(
            5 + triangle(frame, 18U, 4 + energy / 10U)
        );
    } else if (face == MOOD_FACE_CALM) {
        target->left_eye_width = target->right_eye_width = 82 + breath;
        target->left_eye_height = target->right_eye_height = 11;
        target->mouth_width = 64 + breath * 2;
        target->mouth_height = 30;
        target->mouth_y = 80 + breath / 2;
        target->mouth_curve = 1;
        target->color_lift = (uint8_t)triangle(frame, 75U, 5);
    } else if (face == MOOD_FACE_SAD) {
        int drift = triangle(frame, 70U, drive);
        target->left_eye_width = target->right_eye_width = 76;
        target->left_eye_height = target->right_eye_height = 13;
        target->left_eye_y = -61 + drift;
        target->right_eye_y = -57 + drift;
        target->left_eye_rotation = -140;
        target->right_eye_rotation = 140;
        target->mouth_width = 72 - drift;
        target->mouth_height = 34;
        target->mouth_y = 94 + drift;
        target->mouth_curve = -1;
        target->accent_visible = true;
        target->accent_width = 13;
        target->accent_height = 24 + triangle(frame, 35U, 20);
        target->accent_x = 181;
        target->accent_y = -17 + triangle(frame, 35U, 36);
        target->color_lift = 0;
    } else if (face == MOOD_FACE_ANXIOUS) {
        int jitter = signed_swing(frame, 8U, drive);
        target->left_eye_width = target->right_eye_width = 44;
        target->left_eye_height = target->right_eye_height = 58 + breath;
        target->left_eye_curve = target->right_eye_curve = 2;
        target->left_eye_x += jitter;
        target->right_eye_x += jitter;
        target->mouth_width = 74 + triangle(frame, 10U, drive * 2);
        target->mouth_height = 12 + triangle(frame, 10U, drive);
        target->accent_visible = true;
        target->accent_width = 16;
        target->accent_height = 26;
        target->accent_x = 214 + jitter;
        target->accent_y = -92 + triangle(frame, 16U, 18);
        target->color_lift = (uint8_t)triangle(
            frame, 10U, 3 + energy / 12U
        );
    } else if (face == MOOD_FACE_ANGRY) {
        int pulse = triangle(frame, 20U, drive * 2);
        target->left_eye_width = target->right_eye_width = 96 + pulse;
        target->left_eye_height = target->right_eye_height = 15;
        target->left_eye_y = target->right_eye_y = -58 + pulse / 3;
        target->left_eye_rotation = 210;
        target->right_eye_rotation = -210;
        target->mouth_width = 88 + pulse;
        target->mouth_height = 15 + pulse / 3;
        target->mouth_y = 91 - pulse / 3;
        target->color_lift = (uint8_t)triangle(
            frame, 20U, 4 + energy / 10U
        );
    } else if (face == MOOD_FACE_DISGUSTED) {
        int recoil = triangle(frame, 34U, drive * 2);
        target->left_eye_width = 72 + recoil;
        target->left_eye_height = 32;
        target->left_eye_curve = -1;
        target->right_eye_height = 12;
        target->right_eye_width = 70 - recoil;
        target->right_eye_rotation = -120;
        target->mouth_width = 70 - recoil;
        target->mouth_height = 28;
        target->mouth_x = 25 + recoil;
        target->mouth_y = 88 + recoil / 2;
        target->mouth_curve = -1;
        target->color_lift = (uint8_t)triangle(frame, 34U, 6);
    } else if (face == MOOD_FACE_EMBARRASSED) {
        int hide = triangle(frame, 42U, drive * 2);
        target->left_eye_width = target->right_eye_width = 72;
        target->left_eye_height = target->right_eye_height = 30 - hide / 3;
        target->left_eye_curve = target->right_eye_curve = -1;
        target->left_eye_y = target->right_eye_y = -58 + hide;
        target->mouth_width = 54 + breath;
        target->mouth_height = 12;
        target->mouth_y = 90 + hide / 2;
        target->cheek_opacity = (uint8_t)(120 + triangle(frame, 20U, 85));
        target->color_lift = (uint8_t)triangle(frame, 42U, 8);
    } else if (face == MOOD_FACE_OFFLINE) {
        target->left_eye_height = target->right_eye_height = 8;
        target->mouth_width = 64;
        target->mouth_height = 8;
        target->color_lift = 0;
        target->face_opacity = 180;
    } else {
        target->left_eye_width = target->right_eye_width = 22 + breath / 2;
        target->left_eye_height = target->right_eye_height = 26 + breath / 2;
        target->mouth_y += breath / 2;
        int glance = signed_swing(frame, 80U, 3);
        target->left_eye_x += glance;
        target->right_eye_x += glance;
        target->color_lift = (uint8_t)triangle(frame, 80U, 3);
    }

    if (blink(frame, face, energy)) {
        target->left_eye_height = 8;
        target->right_eye_height = 8;
        target->left_eye_curve = 0;
        target->right_eye_curve = 0;
        target->pupils_visible = false;
    }
}
