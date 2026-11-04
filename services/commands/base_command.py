class Command:
    description = "Action"
    selected_trigger = None

    def undo(self):
        raise NotImplementedError

    def redo(self):
        raise NotImplementedError
