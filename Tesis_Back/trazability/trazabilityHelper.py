from django.utils import timezone
from .models import Trazability, Move

class TrazabilityHelper:
    """
    Helper para crear movimientos de trazabilidad fácilmente
    """
    
    @staticmethod
    def ensure_trazability(causa):
        """Asegura que la causa tenga trazabilidad"""
        trazability, created = Trazability.objects.get_or_create(causa=causa)
        return trazability

    @staticmethod
    def register_move(
        causa,
        user,
        action: str,
        entity_type: str,
        previous_value: str = '',
        summary: str = ''
    ):
        """
        Registra un nuevo movimiento
        
        Args:
            causa: Instancia de Causa
            user: Usuario que realizó la acción
            action: Tipo de acción (create, update, delete, etc.)
            entity_type: Tipo de entidad (causa, parte, documento, task, otro)
            previous_value: Valor anterior (opcional)
            summary: Resumen del cambio (opcional)
        
        Returns:
            Move: Instancia del movimiento creado
        """
        trazability = TrazabilityHelper.ensure_trazability(causa)
        
        user_name = user.get_full_name() or user.username if user else 'Sistema'
        
        move = Move.objects.create(
            trazability=trazability,
            causa=causa,
            user=user,
            user_name=user_name,
            timestamp=timezone.now(),
            action=action,
            entity_type=entity_type,
            previous_value=previous_value,
            summary=summary
        )
        
        return move

    # ============================================
    # OPERACIONES SOBRE CAUSA
    # ============================================
    
    @staticmethod
    def register_causa_create(causa, user):
        """Registra creación de causa"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.CREATE,
            entity_type=Move.MoveEntityType.CAUSA,
            summary=f"Se creó la causa {causa.numero_expediente}"
        )

    @staticmethod
    def register_causa_update(causa, user, field_name, old_value, new_value):
        """Registra actualización de un campo de la causa"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.UPDATE,
            entity_type=Move.MoveEntityType.CAUSA,
            previous_value=str(old_value),
            summary=f"Se modificó {field_name} de '{old_value}' a '{new_value}'"
        )

    @staticmethod
    def register_status_change(causa, user, old_status, new_status):
        """Registra cambio de estado"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.STATUS_CHANGE,
            entity_type=Move.MoveEntityType.CAUSA,
            previous_value=old_status,
            summary=f"Se cambió el estado de '{old_status}' a '{new_status}'"
        )

    @staticmethod
    def register_causa_delete(causa, user):
        """Registra eliminación de causa"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.DELETE,
            entity_type=Move.MoveEntityType.CAUSA,
            summary=f"Se eliminó la causa {causa.numero_expediente}"
        )

    # ============================================
    # OPERACIONES SOBRE PARTES
    # ============================================

    @staticmethod
    def register_parte_add(causa, user, parte_nombre, tipo_parte):
        """Registra agregar una parte"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.ADD,
            entity_type=Move.MoveEntityType.PARTE,
            summary=f"Se agregó {tipo_parte}: {parte_nombre}"
        )

    @staticmethod
    def register_parte_update(causa, user, parte_nombre, field_name, old_value, new_value):
        """Registra modificación de una parte"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.UPDATE,
            entity_type=Move.MoveEntityType.PARTE,
            previous_value=str(old_value),
            summary=f"Se modificó {field_name} de {parte_nombre}: de '{old_value}' a '{new_value}'"
        )

    @staticmethod
    def register_parte_remove(causa, user, parte_nombre, tipo_parte):
        """Registra remover una parte"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.REMOVE,
            entity_type=Move.MoveEntityType.PARTE,
            summary=f"Se removió {tipo_parte}: {parte_nombre}"
        )

    # ============================================
    # OPERACIONES SOBRE DOCUMENTOS
    # ============================================

    @staticmethod
    def register_document_upload(causa, user, documento_nombre, tipo_documento=''):
        """Registra carga de documento"""
        tipo_text = f" ({tipo_documento})" if tipo_documento else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.ADD,
            entity_type=Move.MoveEntityType.DOCUMENTO,
            summary=f"Se subió el documento: {documento_nombre}{tipo_text}"
        )

    @staticmethod
    def register_document_update(causa, user, documento_nombre, field_name, old_value, new_value):
        """Registra modificación de metadatos de documento"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.UPDATE,
            entity_type=Move.MoveEntityType.DOCUMENTO,
            previous_value=str(old_value),
            summary=f"Se modificó {field_name} del documento '{documento_nombre}': de '{old_value}' a '{new_value}'"
        )

    @staticmethod
    def register_document_delete(causa, user, documento_nombre):
        """Registra eliminación de documento"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.DELETE,
            entity_type=Move.MoveEntityType.DOCUMENTO,
            summary=f"Se eliminó el documento: {documento_nombre}"
        )

    # ============================================
    # OPERACIONES SOBRE TAREAS
    # ============================================

    @staticmethod
    def register_task_create(causa, user, task_title, priority=''):
        """Registra creación de tarea"""
        priority_text = f" (Prioridad: {priority})" if priority else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.CREATE,
            entity_type=Move.MoveEntityType.TASK,
            summary=f"Se creó la tarea: {task_title}{priority_text}"
        )

    @staticmethod
    def register_task_update(causa, user, task_title, field_name, old_value, new_value):
        """Registra actualización de tarea"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.UPDATE,
            entity_type=Move.MoveEntityType.TASK,
            previous_value=str(old_value),
            summary=f"Se modificó {field_name} de la tarea '{task_title}': de '{old_value}' a '{new_value}'"
        )

    @staticmethod
    def register_task_complete(causa, user, task_title):
        """Registra tarea completada"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.STATUS_CHANGE,
            entity_type=Move.MoveEntityType.TASK,
            previous_value='pendiente',
            summary=f"Se marcó como completada la tarea: {task_title}"
        )

    @staticmethod
    def register_task_delete(causa, user, task_title):
        """Registra eliminación de tarea"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.DELETE,
            entity_type=Move.MoveEntityType.TASK,
            summary=f"Se eliminó la tarea: {task_title}"
        )
    
    # ============================================
    # OPERACIONES SOBRE EVENTOS PROCESALES
    # ============================================

    @staticmethod
    def register_evento_create(causa, user, evento_descripcion, fecha_evento=''):
        """Registra creación de evento procesal"""
        fecha_text = f" - Fecha: {fecha_evento}" if fecha_evento else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.CREATE,
            entity_type=Move.MoveEntityType.EVENTO,
            summary=f"Se creó el evento procesal: {evento_descripcion}{fecha_text}"
        )

    @staticmethod
    def register_evento_update(causa, user, evento_descripcion, field_name, old_value, new_value):
        """Registra actualización de evento procesal"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.UPDATE,
            entity_type=Move.MoveEntityType.EVENTO,
            previous_value=str(old_value),
            summary=f"Se modificó {field_name} del evento '{evento_descripcion}': de '{old_value}' a '{new_value}'"
        )

    @staticmethod
    def register_evento_delete(causa, user, evento_descripcion, fecha_evento=''):
        """Registra eliminación de evento procesal"""
        fecha_text = f" ({fecha_evento})" if fecha_evento else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.DELETE,
            entity_type=Move.MoveEntityType.EVENTO,
            summary=f"Se eliminó el evento procesal: {evento_descripcion}{fecha_text}"
        )
    
    # ============================================
    # OPERACIONES SOBRE RESÚMENES DE IA
    # ============================================

    @staticmethod
    def register_resumen_create(causa, user, tipo_resumen='', tokens_usados=''):
        """
        Registra creación de resumen por IA
        
        Args:
            causa: Instancia de Causa
            user: Usuario que solicitó el resumen
            tipo_resumen: Tipo de resumen (documento, causa, evento, etc.)
            tokens_usados: Cantidad de tokens utilizados (opcional)
        """
        tokens_text = f" - Tokens: {tokens_usados}" if tokens_usados else ""
        tipo_text = f" de {tipo_resumen}" if tipo_resumen else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.CREATE,
            entity_type=Move.MoveEntityType.RESUMEN_IA,
            summary=f"Se generó resumen por IA{tipo_text}{tokens_text}"
        )

    @staticmethod
    def register_resumen_update(causa, user, tipo_resumen='', motivo='regeneración'):
        """
        Registra actualización/regeneración de resumen por IA
        
        Args:
            causa: Instancia de Causa
            user: Usuario que solicitó la actualización
            tipo_resumen: Tipo de resumen actualizado
            motivo: Motivo de la actualización (regeneración, edición manual, etc.)
        """
        tipo_text = f" de {tipo_resumen}" if tipo_resumen else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.UPDATE,
            entity_type=Move.MoveEntityType.RESUMEN_IA,
            summary=f"Se actualizó resumen por IA{tipo_text} - Motivo: {motivo}"
        )

    @staticmethod
    def register_resumen_delete(causa, user, tipo_resumen=''):
        """Registra eliminación de resumen de IA"""
        tipo_text = f" de {tipo_resumen}" if tipo_resumen else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.DELETE,
            entity_type=Move.MoveEntityType.RESUMEN_IA,
            summary=f"Se eliminó resumen por IA{tipo_text}"
        )

    @staticmethod
    def register_resumen_documento(causa, user, documento_nombre, tokens_usados='', modelo=''):
        """Registra resumen de documento específico"""
        tokens_text = f" ({tokens_usados} tokens)" if tokens_usados else ""
        modelo_text = f" - Modelo: {modelo}" if modelo else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.CREATE,
            entity_type=Move.MoveEntityType.RESUMEN_IA,
            summary=f"Se generó resumen del documento '{documento_nombre}'{tokens_text}{modelo_text}"
        )

    @staticmethod
    def register_resumen_causa_completa(causa, user, num_documentos=0, tokens_usados=''):
        """Registra resumen completo de la causa"""
        docs_text = f" ({num_documentos} documentos analizados)" if num_documentos else ""
        tokens_text = f" - {tokens_usados} tokens" if tokens_usados else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.CREATE,
            entity_type=Move.MoveEntityType.RESUMEN_IA,
            summary=f"Se generó resumen completo de la causa{docs_text}{tokens_text}"
        )

    @staticmethod
    def register_resumen_regenerado(causa, user, tipo_resumen='', motivo_regeneracion=''):
        """Registra regeneración de resumen (por cambios en documentos, etc.)"""
        tipo_text = f" de {tipo_resumen}" if tipo_resumen else ""
        motivo_text = f" - Motivo: {motivo_regeneracion}" if motivo_regeneracion else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.UPDATE,
            entity_type=Move.MoveEntityType.RESUMEN_IA,
            previous_value='resumen anterior',
            summary=f"Se regeneró resumen por IA{tipo_text}{motivo_text}"
        )

    @staticmethod
    def register_resumen_editado_manual(causa, user, tipo_resumen=''):
        """Registra cuando el usuario edita manualmente un resumen generado por IA"""
        tipo_text = f" de {tipo_resumen}" if tipo_resumen else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.UPDATE,
            entity_type=Move.MoveEntityType.RESUMEN_IA,
            summary=f"Se editó manualmente el resumen{tipo_text}"
        )

    @staticmethod
    def register_resumen_error(causa, user, tipo_resumen='', error_msg=''):
        """Registra error al generar resumen"""
        tipo_text = f" de {tipo_resumen}" if tipo_resumen else ""
        error_text = f" - Error: {error_msg}" if error_msg else ""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=Move.MoveAction.CREATE,
            entity_type=Move.MoveEntityType.RESUMEN_IA,
            summary=f"Error al generar resumen{tipo_text}{error_text}"
        )
    
    # ============================================
    # OPERACIONES GENÉRICAS
    # ============================================

    @staticmethod
    def register_generic_action(causa, user, action, entity_type, summary, previous_value=''):
        """Registra una acción genérica (para casos específicos)"""
        return TrazabilityHelper.register_move(
            causa=causa,
            user=user,
            action=action,
            entity_type=entity_type,
            previous_value=previous_value,
            summary=summary
        )