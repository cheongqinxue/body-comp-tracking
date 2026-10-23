"""Tests for the Extractor class."""

from pathlib import Path

import pytest

from data_model import BodyComposition, BodyCompositionMultipleScan
from extract import Extractor
from .fuzzy_compare import assert_body_composition_multiple_scan_close

TESTS_DIR = Path(__file__).parent
SAMPLE_IMAGES_DIR = TESTS_DIR

# Fill in expected values for each sample image before running assertions.
EXPECTED_BY_IMAGE: dict[str, BodyCompositionMultipleScan] = {
    "samples/fa019548-74fb-43a1-b9ba-ebe33f7b4817.jpeg": BodyCompositionMultipleScan(
        scans=[
            BodyComposition(
                date="2026-06-20",
                age=35,
                gender="female",
                weight=44.3,
                height=154.0,
                body_fat_percentage=30.9,
                visceral_fat_rating=3,
                muscle_mass=29.1,
                bone_mass=1.5,
                body_mass_index=18.7,
                basal_metabolic_rate_kj=3870,
                total_body_water=20.6,
                total_body_water_percentage=46.5,
                fat_free_mass=30.6,
            ),
            BodyComposition(
                date="2026-07-11",
                age=35,
                gender="female",
                weight=43.5,
                height=154.0,
                body_fat_percentage=29.3,
                visceral_fat_rating=2,
                muscle_mass=29.3,
                bone_mass=1.5,
                body_mass_index=18.3,
                basal_metabolic_rate_kj=3866,
                total_body_water=20.8,
                total_body_water_percentage=47.8,
                fat_free_mass=30.8,
            ),
        ]
    ),
}


class TestExtractor:
    """Tests for body composition extraction from sample images."""

    @pytest.fixture
    def extractor(self) -> Extractor:
        """Create an Extractor instance for tests.

        Returns:
            A new Extractor instance.
        """
        return Extractor()

    @pytest.mark.parametrize("image_name", EXPECTED_BY_IMAGE.keys())
    @pytest.mark.asyncio
    async def test_extract(
        self,
        extractor: Extractor,
        image_name: str,
    ) -> None:
        """Extract body composition from a sample image and compare to expected values.

        Args:
            extractor: Extractor instance under test.
            image_name: Filename of the sample image in the tests directory.
        """
        image_path = SAMPLE_IMAGES_DIR / image_name
        expected = EXPECTED_BY_IMAGE[image_name]

        result = await extractor.extract(str(image_path))

        assert_body_composition_multiple_scan_close(result, expected)

    @pytest.mark.parametrize("image_name", EXPECTED_BY_IMAGE.keys())
    def test_encode_image(self, extractor: Extractor, image_name: str) -> None:
        """Verify encode_image returns a base64 data URL for sample images.

        Args:
            extractor: Extractor instance under test.
            image_name: Filename of the sample image in the tests directory.
        """
        image_path = SAMPLE_IMAGES_DIR / image_name

        data_url = extractor.encode_image(str(image_path))

        assert data_url.startswith("data:image/png;base64,")
        assert len(data_url) > len("data:image/png;base64,")
