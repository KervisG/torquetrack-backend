"""`GET /api/vin/decode`, matching `app/api/vin/decode/route.ts`.

NHTSA vPIC `DecodeVinValuesExtended` is a free, keyless government API —
no credential/env var is needed (spec: "Integration Parity Per Provider",
NHTSA row, env vars: none).
"""
import re
from urllib.parse import quote

import requests
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
NHTSA_DECODE_URL = (
    "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/{vin}?format=json"
)


class VinDecodeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        vin = (request.query_params.get("vin") or "").strip().upper()
        if not VIN_PATTERN.match(vin):
            return Response({"error": "VIN must contain 17 valid characters"}, status=400)

        try:
            upstream = requests.get(
                NHTSA_DECODE_URL.format(vin=quote(vin)),
                timeout=10,
            )
        except requests.RequestException:
            return Response({"error": "VIN verification failed"}, status=502)

        if not upstream.ok:
            return Response({"error": "VIN service unavailable"}, status=502)

        try:
            payload = upstream.json()
        except ValueError:
            return Response({"error": "VIN verification failed"}, status=502)

        results = (payload or {}).get("Results") or []
        vehicle_result = results[0] if results else None
        if not vehicle_result:
            return Response({"error": "Vehicle not found"}, status=404)

        return Response(
            {
                "vehicle": {
                    "vin": vin,
                    "year": vehicle_result.get("ModelYear") or "",
                    "make": vehicle_result.get("Make") or "",
                    "model": vehicle_result.get("Model") or "",
                    "engine": vehicle_result.get("DisplacementL")
                    or vehicle_result.get("EngineModel")
                    or "",
                    "engineModel": vehicle_result.get("EngineModel") or "",
                    "fuelType": vehicle_result.get("FuelTypePrimary") or "",
                }
            }
        )
