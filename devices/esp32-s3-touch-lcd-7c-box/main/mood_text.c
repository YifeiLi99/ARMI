#include "mood_text.h"

#define FRAME_MS 80U

static const char *const EXPRESSIONS[] = {
    "(^o^)",   /* joy */
    "(-v-)",   /* contentment */
    "(o.o)",   /* interest */
    "(^_^)",   /* hope */
    "(-.-)",   /* relief */
    "(<3_<3)", /* affection */
    "(^.^)",   /* gratitude */
    "(-w-)",   /* pride */
    "(O_O)",   /* surprise */
    "(T_T)",   /* sadness */
    "(O~O)",   /* fear */
    "(@_@)",   /* anxiety */
    "(>_<)",   /* anger */
    "(>~<)",   /* frustration */
    "(-_-;)",  /* disgust */
    "(//_//)", /* shame */
    "(;_;)",   /* guilt */
    "(<_<)",   /* jealousy */
    "(-_-)",   /* boredom */
    "(o_O)?",  /* confusion */
    "(._.)",   /* neutral */
    "(- -)",   /* offline */
};

static uint8_t triangle(uint32_t frame, uint32_t period, uint8_t amplitude)
{
    uint32_t position = frame % period;
    uint32_t half = period / 2U;
    uint32_t value = position <= half ? position : period - position;
    return (uint8_t)(value * amplitude / half);
}

const char *mood_text_expression(mood_face_t face)
{
    if (face < MOOD_FACE_JOY || face > MOOD_FACE_OFFLINE) {
        return EXPRESSIONS[MOOD_FACE_NEUTRAL];
    }
    return EXPRESSIONS[face];
}

void mood_text_frame(
    mood_face_t face,
    uint8_t energy,
    uint32_t elapsed_ms,
    mood_text_frame_t *target
)
{
    target->text = mood_text_expression(face);
    if (face == MOOD_FACE_OFFLINE) {
        target->color_lift = 0;
        target->opacity = 180;
        return;
    }
    uint32_t frame = elapsed_ms / FRAME_MS;
    target->color_lift = triangle(frame, 50U, (uint8_t)(2U + energy / 18U));
    target->opacity = elapsed_ms >= 320U ? 255U :
                      (uint8_t)(96U + elapsed_ms * 159U / 320U);
}
