# Ejemplos de idioma

La regla completa está en `../SKILL.md`. Acá van los casos concretos, separados por stack.

## Backend (Python, Django, DRF)

### Correcto

```python
class AdminCustomerTaxStatusView(APIView):
    """`POST /api/admin/customers/<id>/tax-status/`.

    Marcar una exención como VERIFIED hace que el checkout deje de cobrar
    impuesto a ese cliente, así que exige `tax_exemptions.review` y no
    alcanza con ser empleado activo.
    """

    def post(self, request, customer_id):
        # El estado llega del body y no de la URL porque el panel manda los
        # tres valores por el mismo endpoint.
        status_value = request.data.get("status")
```

Identificadores, ruta, nombre del permiso y clave JSON en inglés. Docstring y comentario en español, y explican por qué existe la restricción, no qué hace la línea.

```python
def next_document_number(key: str, prefix: str) -> str:
    # Se bloquea la fila de `DocumentSequence` con `select_for_update()` en
    # lugar de calcular `max()+1`: dos checkouts simultáneos leerían el mismo
    # máximo y emitirían el mismo número.
```

### Incorrecto

```python
# Gets the customer by id            <- comentario en inglés
def obtener_cliente(id_cliente):      # <- identificadores en español
    """Devuelve el cliente."""        # <- docstring que no aporta el porqué
    return Cliente.objects.get(pk=id_cliente)
```

```python
return Response({"error": "El carrito está vacío"}, status=400)
```

Ese texto lo lee un comprador estadounidense. Va `{"error": "Cart is empty"}`.

## Frontend (TypeScript, React)

### Correcto

```tsx
// La cotización se revalida al volver al foco porque un empleado puede
// haberla convertido en orden desde el panel mientras el cliente la mira.
export function QuoteDetailPage() {
  const { data: quote } = useQuery({ queryKey: quoteKeys.detail(token) });

  if (!quote) {
    return <EmptyState message="Quote not found" />;
  }
}
```

Componente, hook, clave de query y texto de pantalla en inglés. Comentario en español, y explica una decisión que no se ve en el código.

### Incorrecto

```tsx
// Renders the quote detail page          <- comentario en inglés y redundante
export function PaginaDetalleCotizacion() {   // <- componente en español
  return <EmptyState message="Cotización no encontrada" />;  // <- UI en español
}
```

## Rutas y archivos

| Correcto | Incorrecto |
|---|---|
| `src/features/quotes/pages/quote-detail-page.tsx` | `src/features/cotizaciones/paginas/pagina-detalle.tsx` |
| `/checkout`, `/account`, `/about` | `/pagar`, `/cuenta`, `/nosotros` |
| `apps/checkout/services/payments.py` | `apps/pagos/servicios/pagos.py` |
| `addToCart`, `getProductById` | `agregarAlCarrito`, `obtenerProductoPorId` |

## Cuándo no poner comentario

El comentario se justifica cuando explica algo que el código no puede mostrar. Si se puede borrar sin perder información, sobra.

```python
# Suma el subtotal y el core            <- sobra, la línea ya lo dice
total = subtotal + core_total

# El core se suma a la base imponible porque TaxJar lo trata como parte
# del precio de venta, no como un depósito reembolsable.
taxable_amount = money(subtotal + core_charge)
```
