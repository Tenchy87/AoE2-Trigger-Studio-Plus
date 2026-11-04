class UndoManager:
    def __init__(self):
        self._undo_stack = []
        self._redo_stack = []

    def execute(self, command):
        command.redo()
        self._undo_stack.append(command)
        self._redo_stack.clear()
        return command

    def undo(self):
        if not self._undo_stack:
            return None

        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        return command

    def redo(self):
        if not self._redo_stack:
            return None

        command = self._redo_stack.pop()
        command.redo()
        self._undo_stack.append(command)
        return command

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()

    def can_undo(self):
        return bool(self._undo_stack)

    def can_redo(self):
        return bool(self._redo_stack)

    def undo_text(self):
        if not self._undo_stack:
            return ""
        return self._undo_stack[-1].description

    def redo_text(self):
        if not self._redo_stack:
            return ""
        return self._redo_stack[-1].description
