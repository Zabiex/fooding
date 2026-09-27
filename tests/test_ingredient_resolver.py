"""Tests for constrained ingredient candidate resolution."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from calorie_bot.domain.models import Ingredient
from calorie_bot.services.ingredient_resolver import (
    IngredientDecision,
    IngredientResolution,
    IngredientResolver,
)


@pytest.mark.asyncio
async def test_resolver_accepts_only_confident_ids_from_candidate_set():
    accepted_id = uuid4()
    rejected_id = uuid4()
    hallucinated_id = uuid4()

    class FakeRepository:
        async def find_ingredient_alias_id(self, name):
            return None

        async def find_ingredient_candidates(self, name, *, limit):
            assert limit == 12
            return [{"id": accepted_id, "name": "egg"}, {"id": rejected_id, "name": "onion"}]

    class FakeAgent:
        async def run(self, prompt):
            payload = json.loads(prompt)
            assert [item["input_index"] for item in payload] == [0, 1, 2]
            return SimpleNamespace(
                output=IngredientResolution(
                    decisions=[
                        IngredientDecision(
                            input_index=0,
                            existing_ingredient_id=accepted_id,
                            confidence=0.97,
                        ),
                        IngredientDecision(
                            input_index=1,
                            existing_ingredient_id=rejected_id,
                            confidence=0.72,
                        ),
                        IngredientDecision(
                            input_index=2,
                            existing_ingredient_id=hallucinated_id,
                            confidence=0.99,
                        ),
                    ]
                )
            )

    resolver = IngredientResolver.__new__(IngredientResolver)
    resolver._agent = FakeAgent()
    resolved = await resolver.resolve(
        FakeRepository(),
        [Ingredient(name="large egg"), Ingredient(name="scallion"), Ingredient(name="fresh herb")],
    )

    assert resolved == [accepted_id, None, None]