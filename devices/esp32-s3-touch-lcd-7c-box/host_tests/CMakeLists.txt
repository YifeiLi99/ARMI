cmake_minimum_required(VERSION 3.16)
project(armi_mood_display_host_tests C)

enable_testing()
find_package(cJSON CONFIG REQUIRED)
add_executable(
    mood_display_host_tests
    test_mood_display.c
    ../main/mood_text.c
    ../main/mood_offline.c
    ../main/mood_protocol.c
)
target_include_directories(mood_display_host_tests PRIVATE ../main)
target_link_libraries(mood_display_host_tests PRIVATE cjson)
add_test(NAME mood_display_host_tests COMMAND mood_display_host_tests)
