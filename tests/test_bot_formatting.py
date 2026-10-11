from calorie_bot.bot.formatting import format_exercise_list
from calorie_bot.domain.models import Exercise


def test_format_exercise_list_includes_names_and_muscle_groups():
    exercises = [
        Exercise(
            exercise_id="11111111-1111-1111-1111-111111111111",
            name="Bench press",
            muscle_groups=["chest", "triceps"],
        )
    ]

    rendered = format_exercise_list(exercises)

    assert "Bench press" in rendered
    assert "chest, triceps" in rendered


def test_format_exercise_list_handles_empty_catalog():
    assert format_exercise_list([]) == "There are no exercises in the catalog yet."