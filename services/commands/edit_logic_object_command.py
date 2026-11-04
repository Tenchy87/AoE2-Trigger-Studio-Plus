from services.commands.base_command import Command


class EditLogicObjectCommand(Command):
    def __init__(
        self,
        logic_object,
        old_values,
        new_values,
        selected_trigger,
        description="Edit Trigger Logic",
    ):
        self.logic_object = logic_object
        self.old_values = dict(old_values)
        self.new_values = dict(new_values)
        self.selected_trigger = selected_trigger
        self.selected_logic_object = logic_object
        self.description = description

    def _apply(self, values):
        for field_name, value in values.items():
            setattr(
                self.logic_object,
                field_name,
                value,
            )

    def undo(self):
        self._apply(self.old_values)

    def redo(self):
        self._apply(self.new_values)
