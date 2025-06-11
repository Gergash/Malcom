import re

class BINValidator:
    def __init__(self):
        self.bin_pattern = re.compile(r'^\d{6,8}$')

    def validate_format(self, bin_number: str) -> bool:
        """
        Valida el formato del BIN:
        - Debe contener solo dígitos
        - Longitud entre 6 y 8 dígitos
        """
        if not isinstance(bin_number, str):
            bin_number = str(bin_number)
        
        return bool(self.bin_pattern.match(bin_number))

    def validate_luhn(self, bin_number: str) -> bool:
        """
        Implementa el algoritmo de Luhn para validar el BIN
        """
        if not isinstance(bin_number, str):
            bin_number = str(bin_number)
            
        digits = [int(d) for d in bin_number]
        checksum = 0
        is_odd = True

        for d in digits[::-1]:
            if is_odd:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
            is_odd = not is_odd

        return checksum % 10 == 0

    def get_validation_level(self, bin_number: str) -> str:
        """
        Determina el nivel de validación del BIN:
        - 'HIGH': Pasa validación de formato y Luhn
        - 'MEDIUM': Solo pasa validación de formato
        - 'LOW': No pasa ninguna validación
        """
        if not isinstance(bin_number, str):
            bin_number = str(bin_number)

        if not self.validate_format(bin_number):
            return 'LOW'
        
        return 'HIGH' if self.validate_luhn(bin_number) else 'MEDIUM' 