#include "mood_animation.h"

#include <stdbool.h>
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
    if (face == MOOD_FACE_OFFLINE || face == MOOD_FACE_CONTENTMENT ||
        face == MOOD_FACE_BOREDOM) {
        return false;
    }
    uint32_t period = (face == MOOD_FACE_FEAR || face == MOOD_FACE_ANXIETY) ? 31U :
                      face == MOOD_FACE_SURPRISE ? 47U : 59U;
    uint32_t closed_frames = energy >= 60U ? 2U : 1U;
    return (frame + period / 2U) % period < closed_frames;
}

static void base_frame(mood_animation_frame_t *target)
{
    memset(target, 0, sizeof(*target));
    target->left_eye = MOOD_EYE_DOT;
    target->right_eye = MOOD_EYE_DOT;
    target->mouth = MOOD_MOUTH_SMALL_SMILE;
    target->eye_y = 40;
    target->eye_spread = 34;
    target->eye_scale = 100;
    target->mouth_y = 80;
    target->mouth_scale_x = 100;
    target->mouth_scale_y = 100;
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
    int drive = 1 + (int)energy / 35;
    int breath = triangle(frame, 50U, drive);
    target->face_y = breath / 2;
    target->color_lift = (uint8_t)triangle(frame, 50U, 2 + energy / 18U);
    target->face_opacity = elapsed_ms >= 320U ? 255U :
                           (uint8_t)(96U + elapsed_ms * 159U / 320U);

    switch (face) {
    case MOOD_FACE_JOY:
        target->left_eye = target->right_eye = MOOD_EYE_CAP;
        target->mouth = MOOD_MOUTH_OPEN_SMILE;
        target->eye_scale = 100 + breath * 2;
        target->mouth_scale_x = 100 + breath * 2;
        target->mouth_y = 78 - breath / 2;
        target->cheek_opacity = (uint8_t)(65 + triangle(frame, 50U, 45));
        break;
    case MOOD_FACE_CONTENTMENT:
        target->left_eye = target->right_eye = MOOD_EYE_FLAT;
        target->mouth = MOOD_MOUTH_SMILE;
        target->eye_scale = 100 + breath;
        target->mouth_scale_x = 92 + breath * 2;
        target->mouth_y = 81 + breath / 2;
        target->color_lift = (uint8_t)triangle(frame, 75U, 5);
        break;
    case MOOD_FACE_INTEREST:
        target->eye_scale = 105 + breath * 2;
        target->eye_spread = 33 - breath / 2;
        target->accent = MOOD_ACCENT_SPARKLE;
        target->accent_x = 151;
        target->accent_y = 27;
        break;
    case MOOD_FACE_HOPE:
        target->left_eye = target->right_eye = MOOD_EYE_RAISED;
        target->mouth = MOOD_MOUTH_SMILE;
        target->eye_y = 41 - breath;
        target->face_y = -breath;
        target->accent = MOOD_ACCENT_RISE;
        target->accent_x = 100;
        target->accent_y = 23 - breath;
        break;
    case MOOD_FACE_RELIEF: {
        int release = triangle(frame, 62U, drive);
        target->left_eye = target->right_eye = MOOD_EYE_SOFT;
        target->eye_scale = 94 + release;
        target->mouth_scale_x = 88 + release * 2;
        target->accent = MOOD_ACCENT_EXHALE;
        target->accent_x = 134 + release;
        target->accent_y = 79;
        break;
    }
    case MOOD_FACE_AFFECTION: {
        int beat = triangle(frame, 20U, drive * 2);
        target->left_eye = target->right_eye = MOOD_EYE_HEART;
        target->mouth = MOOD_MOUTH_SMILE;
        target->eye_scale = 94 + beat * 2;
        target->cheek_opacity = (uint8_t)(100 + triangle(frame, 20U, 80));
        break;
    }
    case MOOD_FACE_GRATITUDE:
        target->left_eye = target->right_eye = MOOD_EYE_CAP;
        target->eye_scale = 92 + breath;
        target->face_y = breath;
        target->cheek_opacity = (uint8_t)(45 + triangle(frame, 60U, 35));
        break;
    case MOOD_FACE_PRIDE:
        target->left_eye = target->right_eye = MOOD_EYE_PROUD;
        target->mouth = MOOD_MOUTH_PROUD_SMILE;
        target->face_y = -breath / 2;
        target->eye_scale = 100 + breath;
        break;
    case MOOD_FACE_SURPRISE: {
        int pop = triangle(frame, 24U, drive * 2);
        target->left_eye = target->right_eye = MOOD_EYE_RING;
        target->mouth = MOOD_MOUTH_OPEN;
        target->eye_scale = 100 + pop * 2;
        target->mouth_scale_x = target->mouth_scale_y = 100 + pop * 2;
        if (frame % 43U < 2U) {
            target->face_x = signed_swing(frame, 4U, 1);
        }
        break;
    }
    case MOOD_FACE_SADNESS: {
        int drift = triangle(frame, 70U, drive);
        target->left_eye = MOOD_EYE_SAD_LEFT;
        target->right_eye = MOOD_EYE_SAD_RIGHT;
        target->mouth = MOOD_MOUTH_FROWN;
        target->eye_y = 42 + drift;
        target->mouth_y = 84 + drift;
        target->mouth_scale_x = 95 - drift * 2;
        target->accent = MOOD_ACCENT_TEAR;
        target->accent_x = 145;
        target->accent_y = 54 + triangle(frame, 35U, 18);
        target->color_lift = 0;
        break;
    }
    case MOOD_FACE_FEAR: {
        int jitter = signed_swing(frame, 6U, drive);
        target->left_eye = target->right_eye = MOOD_EYE_RING_DOT;
        target->mouth = MOOD_MOUTH_WAVE;
        target->face_x = jitter;
        target->eye_scale = 108 + triangle(frame, 12U, drive * 2);
        target->mouth_scale_x = 90 + triangle(frame, 8U, drive * 3);
        break;
    }
    case MOOD_FACE_ANXIETY: {
        int jitter = signed_swing(frame, 8U, drive);
        target->mouth = MOOD_MOUTH_WAVE;
        target->face_x = jitter;
        target->eye_scale = 100 + breath * 2;
        target->mouth_scale_x = 100 + triangle(frame, 10U, drive * 3);
        target->accent = MOOD_ACCENT_SWEAT;
        target->accent_x = 158 + jitter;
        target->accent_y = 25 + triangle(frame, 16U, 8);
        target->color_lift = (uint8_t)triangle(frame, 10U, 3 + energy / 14U);
        break;
    }
    case MOOD_FACE_ANGER: {
        int tension = triangle(frame, 20U, drive);
        target->left_eye = MOOD_EYE_GREATER;
        target->right_eye = MOOD_EYE_LESS;
        target->mouth = MOOD_MOUTH_TEETH;
        target->eye_y = 42 + tension / 2;
        target->eye_scale = 100 + tension * 2;
        target->mouth_y = 81 - tension / 2;
        target->mouth_scale_x = 100 + tension * 2;
        target->color_lift = (uint8_t)triangle(frame, 20U, 4 + energy / 12U);
        if (energy >= 60U && frame % 41U < 3U) {
            target->face_x = frame % 2U == 0U ? -1 : 1;
        }
        break;
    }
    case MOOD_FACE_FRUSTRATION: {
        int squeeze = triangle(frame, 26U, drive);
        target->left_eye = MOOD_EYE_GREATER;
        target->right_eye = MOOD_EYE_LESS;
        target->mouth = MOOD_MOUTH_WAVE;
        target->eye_scale = 95 + squeeze * 2;
        target->mouth_y = 83 + squeeze;
        target->accent = MOOD_ACCENT_STRESS;
        target->accent_x = 153;
        target->accent_y = 25;
        break;
    }
    case MOOD_FACE_DISGUST: {
        int recoil = triangle(frame, 34U, drive);
        target->left_eye = MOOD_EYE_HALF;
        target->right_eye = MOOD_EYE_FLAT;
        target->mouth = MOOD_MOUTH_SKEW_FROWN;
        target->eye_shift_x = recoil;
        target->mouth_y = 82 + recoil;
        target->mouth_scale_x = 92 - recoil * 2;
        target->color_lift = (uint8_t)triangle(frame, 34U, 6);
        break;
    }
    case MOOD_FACE_SHAME: {
        int hide = triangle(frame, 42U, drive);
        target->left_eye = target->right_eye = MOOD_EYE_CAP;
        target->mouth = MOOD_MOUTH_FROWN;
        target->eye_y = 42 + hide;
        target->eye_scale = 88 - hide;
        target->mouth_y = 81 + hide / 2;
        target->mouth_scale_x = 82 + breath;
        target->cheek_opacity = (uint8_t)(135 + triangle(frame, 20U, 90));
        target->color_lift = (uint8_t)triangle(frame, 42U, 8);
        break;
    }
    case MOOD_FACE_GUILT: {
        int sink = triangle(frame, 65U, drive);
        target->left_eye = MOOD_EYE_GUILT_LEFT;
        target->right_eye = MOOD_EYE_GUILT_RIGHT;
        target->mouth = MOOD_MOUTH_SMALL_FROWN;
        target->face_y = 2 + sink;
        target->eye_shift_x = -2;
        target->mouth_scale_x = 86 - sink;
        break;
    }
    case MOOD_FACE_JEALOUSY: {
        int glance = signed_swing(frame, 46U, 4);
        target->left_eye = target->right_eye = MOOD_EYE_RING_DOT;
        target->mouth = MOOD_MOUTH_SKEW_FROWN;
        target->eye_shift_x = glance;
        target->mouth_scale_x = 92;
        target->color_lift = (uint8_t)triangle(frame, 23U, 7);
        break;
    }
    case MOOD_FACE_BOREDOM:
        target->left_eye = target->right_eye = MOOD_EYE_FLAT;
        target->mouth = MOOD_MOUTH_FLAT;
        target->face_y = triangle(frame, 110U, 1);
        target->eye_scale = 94;
        target->color_lift = (uint8_t)triangle(frame, 100U, 2);
        break;
    case MOOD_FACE_CONFUSION: {
        int wobble = signed_swing(frame, 34U, 2);
        target->left_eye = MOOD_EYE_DOT;
        target->right_eye = MOOD_EYE_RING;
        target->mouth = MOOD_MOUTH_SKEW_FROWN;
        target->eye_y = 40 + wobble;
        target->eye_shift_x = wobble;
        target->accent = MOOD_ACCENT_QUESTION;
        target->accent_x = 158;
        target->accent_y = 27 + triangle(frame, 40U, 2);
        break;
    }
    case MOOD_FACE_OFFLINE:
        target->left_eye = target->right_eye = MOOD_EYE_FLAT;
        target->mouth = MOOD_MOUTH_NONE;
        target->face_opacity = 180;
        target->color_lift = 0;
        break;
    case MOOD_FACE_NEUTRAL:
    default:
        target->eye_shift_x = signed_swing(frame, 80U, 2);
        target->eye_scale = 100 + breath;
        target->mouth_y = 81 + breath / 2;
        target->color_lift = (uint8_t)triangle(frame, 80U, 3);
        break;
    }

    if (blink(frame, face, energy)) {
        target->left_eye = target->right_eye = MOOD_EYE_FLAT;
    }
}
