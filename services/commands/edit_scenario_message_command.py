from services.commands.base_command import Command


class EditScenarioMessageCommand(Command):
    """Undoable edit of one scenario MessageManager text field."""

    ALLOWED_FIELDS = {
        "instructions",
        "hints",
        "victory",
        "loss",
        "history",
        "scouts",
    }

    def __init__(self, message_manager, field_name, old_value, new_value):
        if field_name not in self.ALLOWED_FIELDS:
            raise ValueError(
                f"Unsupported scenario message field: {field_name}"
            )

        self.message_manager = message_manager
        self.field_name = field_name
        self.old_value = old_value
        self.new_value = new_value
        self.description = f"Edit scenario message: {field_name}"
        self.selected_trigger = None
        self.selected_logic_object = None

    def redo(self):
        setattr(self.message_manager, self.field_name, self.new_value)

    def undo(self):
        setattr(self.message_manager, self.field_name, self.old_value)
