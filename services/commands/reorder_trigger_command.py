from services.commands.base_command import Command


class ReorderTriggerCommand(Command):
    def __init__(
        self,
        trigger_manager,
        old_trigger_order,
        new_trigger_order,
        selected_trigger,
        description="Reorder Trigger",
    ):
        self.trigger_manager = trigger_manager
        self.old_trigger_order = list(old_trigger_order)
        self.new_trigger_order = list(new_trigger_order)
        self.selected_trigger = selected_trigger
        self.description = description

    def _apply(self, trigger_order):
        trigger_ids = [
            trigger.trigger_id
            for trigger in trigger_order
        ]
        self.trigger_manager.reorder_triggers(trigger_ids)

    def undo(self):
        self._apply(self.old_trigger_order)

    def redo(self):
        self._apply(self.new_trigger_order)
