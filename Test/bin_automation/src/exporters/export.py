import pandas as pd
import json
from pathlib import Path

def export_to_json(df: pd.DataFrame, output_path: Path):
    """
    Exporta los datos clasificados a formato JSON
    """
    data = df.to_dict(orient='records')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def create_store_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Crea un resumen agrupado por tienda con estadísticas relevantes
    """
    summary = df.groupby(['store_id', 'country', 'card_type']).agg({
        'bin': 'count',
        'validation_level': lambda x: (x == 'HIGH').mean() * 100
    }).reset_index()
    
    summary.columns = ['store_id', 'country', 'card_type', 'bin_count', 'high_validation_percent']
    return summary

def main():
    try:
        # Cargar datos clasificados
        input_path = Path('data/output/classified.csv')
        df = pd.read_csv(input_path)
        
        # Exportar a JSON
        json_path = Path('data/output/classified.json')
        export_to_json(df, json_path)
        print(f"Datos exportados a JSON en {json_path}")
        
        # Crear y exportar resumen por tienda
        if 'store_id' in df.columns:
            summary_df = create_store_summary(df)
            summary_path = Path('data/output/summary_by_store.csv')
            summary_df.to_csv(summary_path, index=False)
            print(f"Resumen por tienda guardado en {summary_path}")
            
    except Exception as e:
        print(f"Error durante la exportación: {e}")
        raise

if __name__ == '__main__':
    main() 