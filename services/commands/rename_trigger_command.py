from services.commands.base_command import Command


class RenameTriggerCommand(Command):
    def __init__(self, trigger, old_name, new_name):
        self.trigger = trigger
        self.selected_trigger = trigger
        self.old_name = old_name
        self.new_name = new_name
        self.description = f"Rename Trigger to '{new_name}'"

    def undo(self):
        self.trigger.name = self.old_name

    def redo(self):
        self.trigger.name = self.new_name
