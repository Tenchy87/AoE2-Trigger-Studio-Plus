from colorsys import hsv_to_rgb

from PySide6.QtGui import (
    QColor,
    QImage,
)


class MapRenderer:
    """
    High-resolution terrain renderer.

    Designed for export-quality maps rather than
    low-resolution minimaps.
    """

    TERRAIN_COLOURS = {
        0: QColor(76, 128, 68),
        1: QColor(46, 99, 155),
        2: QColor(200, 186, 132),
        3: QColor(141, 117, 84),
        4: QColor(72, 118, 170),
        5: QColor(55, 104, 56),
        10: QColor(53, 91, 49),
        11: QColor(77, 118, 64),
        12: QColor(198, 190, 165),
        13: QColor(214, 207, 181),
        14: QColor(225, 220, 198),
        15: QColor(190, 170, 110),
        24: QColor(210, 188, 128),
        31: QColor(192, 177, 105),
        32: QColor(235, 235, 235),
        33: QColor(220, 220, 220),
        34: QColor(200, 200, 200),
        35: QColor(47, 91, 52),
        36: QColor(54, 102, 58),
        37: QColor(60, 108, 61),
        38: QColor(47, 93, 55),
        45: QColor(49, 90, 152),
        46: QColor(43, 82, 146),
        47: QColor(70, 115, 176),
        48: QColor(87, 136, 198),
        100: QColor(91, 126, 73),
        101: QColor(77, 109, 64),
        102: QColor(64, 101, 58),
    }

    @classmethod
    def render(
        cls,
        scenario,
        tile_scale=8,
    ):
        map_manager = scenario.map_manager

        map_width = map_manager.map_width
        map_height = map_manager.map_height

        image_width = map_width * tile_scale
        image_height = map_height * tile_scale

        image = QImage(
            image_width,
            image_height,
            QImage.Format_RGB32,
        )

        minimum_elevation = None
        maximum_elevation = None

        #
        # PASS 1
        # Determine elevation range.
        #

        for y in range(map_height):

            for x in range(map_width):

                tile = map_manager.get_tile(
                    x,
                    y,
                )

                elevation = tile.elevation

                if minimum_elevation is None:

                    minimum_elevation = elevation
                    maximum_elevation = elevation

                else:

                    minimum_elevation = min(
                        minimum_elevation,
                        elevation,
                    )

                    maximum_elevation = max(
                        maximum_elevation,
                        elevation,
                    )

        minimum_elevation = minimum_elevation or 0
        maximum_elevation = maximum_elevation or 0

        elevation_range = max(
            maximum_elevation
            - minimum_elevation,
            1,
        )

        #
        # PASS 2
        # Render terrain.
        #

        for y in range(map_height):

            for x in range(map_width):

                tile = map_manager.get_tile(
                    x,
                    y,
                )

                terrain_id = (
                    tile.terrain_id
                )

                colour = (
                    cls.get_terrain_colour(
                        terrain_id
                    )
                )

                colour = (
                    cls.apply_elevation_shading(
                        colour,
                        tile.elevation,
                        minimum_elevation,
                        elevation_range,
                    )
                )

                #
                # AoE2 coordinates start
                # bottom-left.
                #

                display_y = (
                    map_height
                    - 1
                    - y
                )

                start_x = (
                    x
                    * tile_scale
                )

                start_y = (
                    display_y
                    * tile_scale
                )

                for py in range(
                    tile_scale
                ):

                    for px in range(
                        tile_scale
                    ):

                        image.setPixelColor(
                            start_x + px,
                            start_y + py,
                            colour,
                        )

        return image

    @classmethod
    def export_png(
        cls,
        scenario,
        output_path,
        tile_scale=8,
    ):
        image = cls.render(
            scenario,
            tile_scale,
        )

        return image.save(
            output_path,
            "PNG",
        )

    @classmethod
    def get_terrain_colour(
        cls,
        terrain_id,
    ):
        if (
            terrain_id
            in cls.TERRAIN_COLOURS
        ):
            return (
                cls.TERRAIN_COLOURS[
                    terrain_id
                ]
            )

        #
        # Unknown terrain IDs
        # get deterministic colours.
        #

        hue = (
            terrain_id
            * 0.61803398875
        ) % 1.0

        red, green, blue = hsv_to_rgb(
            hue,
            0.42,
            0.70,
        )

        return QColor(
            int(red * 255),
            int(green * 255),
            int(blue * 255),
        )

    @staticmethod
    def apply_elevation_shading(
        colour,
        elevation,
        minimum,
        range_value,
    ):
        position = (
            elevation
            - minimum
        ) / range_value

        adjustment = int(
            (
                position
                - 0.5
            )
            * 36
        )

        return QColor(
            max(
                0,
                min(
                    255,
                    colour.red()
                    + adjustment,
                ),
            ),
            max(
                0,
                min(
                    255,
                    colour.green()
                    + adjustment,
                ),
            ),
            max(
                0,
                min(
                    255,
                    colour.blue()
                    + adjustment,
                ),
            ),
        )