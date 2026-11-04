from services.commands.base_command import Command


class AddConditionCommand(Command):
    def __init__(
        self,
        trigger,
        condition_type,
        condition_id,
        condition_kwargs,
        condition_label,
    ):
        self.trigger = trigger
        self.selected_trigger = trigger
        self.condition_type = condition_type
        self.condition_id = condition_id
        self.condition_kwargs = dict(condition_kwargs)
        self.condition_label = condition_label
        self.condition = None
        self.selected_logic_object = None
        self.description = f"Add {condition_label} Condition"

    def redo(self):
        if self.condition_type == "timer":
            self.condition = self.trigger.new_condition.timer(
                **self.condition_kwargs
            )
        else:
            self.condition = self.trigger._add_condition(
                self.condition_id,
                **self.condition_kwargs,
            )

        self.selected_logic_object = self.condition

    def undo(self):
        if self.condition is None:
            return

        self.trigger.remove_condition(
            condition=self.condition
        )
