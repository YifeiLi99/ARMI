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
    target->left_eye_width = 92;
    target->left_eye_height = 54;
    target->left_eye_x = -145;
    target->left_eye_y = -65;
    target->right_eye_width = 92;
    target->right_eye_height = 54;
    target->right_eye_x = 145;
    target->right_eye_y = -65;
    target->pupil_size = 22;
    target->pupils_visible = true;
    target->mouth_width = 180;
    target->mouth_height = 18;
    target->mouth_y = 105;
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
    target->background_lift = (uint8_t)triangle(frame, 50U, 2 + energy / 16U);
    target->face_opacity = elapsed_ms >= 320U ? 255U :
                           (uint8_t)(96U + elapsed_ms * 159U / 320U);

    if (face == MOOD_FACE_HAPPY) {
        target->left_eye_height = 44 + breath;
        target->right_eye_height = 44 + breath;
        target->mouth_width = 230 + breath * 2;
        target->mouth_height = 60 + breath;
        target->mouth_y = 98 - breath;
        target->mouth_curve = 1;
        target->cheek_opacity = (uint8_t)(75 + triangle(frame, 50U, 45));
    } else if (face == MOOD_FACE_EXCITED) {
        int bounce = triangle(frame, 18U, drive * 2);
        target->left_eye_width = target->right_eye_width = 110 + bounce;
        target->left_eye_height = target->right_eye_height = 70 + bounce;
        target->left_eye_y = target->right_eye_y = -65 - bounce / 2;
        target->pupil_size = 27 + bounce / 2;
        target->mouth_width = 260 + bounce * 2;
        target->mouth_height = 78 + bounce;
        target->mouth_y = 94 - bounce;
        target->mouth_curve = 1;
        target->cheek_opacity = (uint8_t)(90 + triangle(frame, 18U, 55));
        target->background_lift = (uint8_t)(
            5 + triangle(frame, 18U, 4 + energy / 10U)
        );
    } else if (face == MOOD_FACE_CALM) {
        target->left_eye_width = target->right_eye_width = 100 + breath;
        target->left_eye_height = target->right_eye_height = 12;
        target->pupils_visible = false;
        target->mouth_width = 170 + breath * 2;
        target->mouth_height = 12;
        target->mouth_y = 104 + breath / 2;
        target->background_lift = (uint8_t)triangle(frame, 75U, 5);
    } else if (face == MOOD_FACE_SAD) {
        int drift = triangle(frame, 70U, drive);
        target->left_eye_width = target->right_eye_width = 72;
        target->left_eye_height = target->right_eye_height = 42 - drift / 2;
        target->left_eye_y = -61 + drift;
        target->right_eye_y = -57 + drift;
        target->pupil_y = 7;
        target->mouth_width = 180 - drift * 2;
        target->mouth_height = 42;
        target->mouth_y = 125 + drift;
        target->mouth_curve = -1;
        target->accent_visible = true;
        target->accent_width = 13;
        target->accent_height = 24 + triangle(frame, 35U, 20);
        target->accent_x = 181;
        target->accent_y = -17 + triangle(frame, 35U, 36);
        target->background_lift = 0;
    } else if (face == MOOD_FACE_ANXIOUS) {
        int jitter = signed_swing(frame, 8U, drive);
        target->left_eye_width = target->right_eye_width = 64;
        target->left_eye_height = target->right_eye_height = 76 + breath;
        target->left_eye_x += jitter;
        target->right_eye_x += jitter;
        target->pupil_x = -jitter * 2;
        target->mouth_width = 116 + triangle(frame, 10U, drive * 3);
        target->mouth_height = 18 + triangle(frame, 10U, drive);
        target->accent_visible = true;
        target->accent_width = 16;
        target->accent_height = 26;
        target->accent_x = 214 + jitter;
        target->accent_y = -92 + triangle(frame, 16U, 18);
        target->background_lift = (uint8_t)triangle(
            frame, 10U, 3 + energy / 12U
        );
    } else if (face == MOOD_FACE_ANGRY) {
        int pulse = triangle(frame, 20U, drive * 2);
        target->left_eye_width = target->right_eye_width = 110 + pulse;
        target->left_eye_height = target->right_eye_height = 34 - pulse / 3;
        target->left_eye_y = target->right_eye_y = -58 + pulse / 3;
        target->pupil_y = 5;
        target->mouth_width = 210 + pulse * 2;
        target->mouth_height = 25 + pulse / 2;
        target->mouth_y = 112 - pulse / 2;
        target->background_lift = (uint8_t)triangle(
            frame, 20U, 4 + energy / 10U
        );
    } else if (face == MOOD_FACE_DISGUSTED) {
        int recoil = triangle(frame, 34U, drive * 2);
        target->left_eye_height = 52 + recoil;
        target->right_eye_height = 24;
        target->right_eye_width = 76 - recoil;
        target->pupil_x = 6;
        target->mouth_width = 150 - recoil * 2;
        target->mouth_height = 30;
        target->mouth_x = 35 + recoil;
        target->mouth_y = 108 + recoil / 2;
        target->mouth_curve = -1;
        target->background_lift = (uint8_t)triangle(frame, 34U, 6);
    } else if (face == MOOD_FACE_EMBARRASSED) {
        int hide = triangle(frame, 42U, drive * 2);
        target->left_eye_width = target->right_eye_width = 70;
        target->left_eye_height = target->right_eye_height = 42 - hide / 2;
        target->left_eye_y = target->right_eye_y = -58 + hide;
        target->pupil_y = 6;
        target->mouth_width = 110 + breath;
        target->mouth_height = 15;
        target->mouth_y = 112 + hide / 2;
        target->cheek_opacity = (uint8_t)(120 + triangle(frame, 20U, 85));
        target->background_lift = (uint8_t)triangle(frame, 42U, 8);
    } else if (face == MOOD_FACE_OFFLINE) {
        target->left_eye_height = target->right_eye_height = 8;
        target->pupils_visible = false;
        target->mouth_width = 150;
        target->mouth_height = 8;
        target->background_lift = 0;
        target->face_opacity = 180;
    } else {
        target->left_eye_height += breath / 2;
        target->right_eye_height += breath / 2;
        target->mouth_y += breath / 2;
        target->pupil_x = signed_swing(frame, 80U, 3);
        target->background_lift = (uint8_t)triangle(frame, 80U, 3);
    }

    if (blink(frame, face, energy)) {
        target->left_eye_height = 8;
        target->right_eye_height = 8;
        target->pupils_visible = false;
    }
}
