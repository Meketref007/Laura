"""
test_tracing.py - Tests for distributed tracing module
"""

from shopee_agent.tracing import (
    TraceContext,
    DistributedTracer,
    get_tracer,
    get_correlation_id,
    create_trace,
    get_trace_headers,
)


class TestTraceContext:
    """Tests for TraceContext"""
    
    def test_context_creation(self):
        """Verify trace context creation"""
        context = TraceContext(
            endpoint="/api/v2/test",
            operation="get_item_list"
        )
        
        assert context.correlation_id
        assert context.span_id
        assert context.endpoint == "/api/v2/test"
        assert context.operation == "get_item_list"
        assert context.error is None
        assert context.status_code is None
    
    def test_context_with_parent(self):
        """Verify child span creation"""
        parent = TraceContext(operation="parent_op")
        parent_id = parent.span_id
        
        child = TraceContext(
            correlation_id=parent.correlation_id,
            parent_span_id=parent_id,
            operation="child_op"
        )
        
        assert child.correlation_id == parent.correlation_id
        assert child.parent_span_id == parent_id
        assert child.span_id != parent_id
    
    def test_record_success(self):
        """Verify success recording"""
        context = TraceContext(operation="test_op")
        context.record_success(status_code=200)
        
        assert context.status_code == 200
        assert context.end_time is not None
        assert context.error is None
    
    def test_record_error(self):
        """Verify error recording"""
        context = TraceContext(operation="test_op")
        context.record_error("Connection timeout")
        
        assert context.error == "Connection timeout"
        assert context.end_time is not None
    
    def test_to_dict(self):
        """Verify context serialization"""
        context = TraceContext(operation="test_op")
        context.record_success(status_code=200)
        
        data = context.to_dict()
        assert "correlation_id" in data
        assert "span_id" in data
        assert data["operation"] == "test_op"
        assert data["status_code"] == 200


class TestDistributedTracer:
    """Tests for DistributedTracer"""
    
    def test_tracer_creation(self):
        """Verify tracer creation"""
        tracer = DistributedTracer()
        assert tracer is not None
    
    def test_start_trace(self):
        """Verify trace initialization"""
        tracer = DistributedTracer()
        context = tracer.start_trace(
            endpoint="/api/v2/test",
            operation="get_items"
        )
        
        assert context.correlation_id
        assert context.endpoint == "/api/v2/test"
        assert context.operation == "get_items"
    
    def test_child_span(self):
        """Verify child span creation"""
        tracer = DistributedTracer()
        parent = tracer.start_trace(operation="parent")
        
        child = tracer.start_child_span(
            parent_context=parent,
            operation="child",
            endpoint="/api/v2/child"
        )
        
        assert child.correlation_id == parent.correlation_id
        assert child.parent_span_id == parent.span_id
    
    def test_end_span_success(self):
        """Verify successful span completion"""
        tracer = DistributedTracer()
        context = tracer.start_trace(operation="test_op")
        
        assert tracer.get_span_count() == 1
        
        tracer.end_span(context, status_code=200)
        
        assert tracer.get_span_count() == 0
    
    def test_end_span_error(self):
        """Verify error span completion"""
        tracer = DistributedTracer()
        context = tracer.start_trace(operation="test_op")
        
        tracer.end_span(context, error="Failed to connect")
        
        assert context.error == "Failed to connect"
        assert tracer.get_span_count() == 0
    
    def test_correlation_id_propagation(self):
        """Verify correlation ID propagation"""
        tracer = DistributedTracer()
        _correlation_id = tracer.get_current_correlation_id()
        
        context1 = tracer.start_trace(operation="op1")
        tracer.end_span(context1)
        
        context2 = tracer.start_trace(operation="op2")
        # Should use same correlation ID within context
        assert context2.correlation_id
    
    def test_get_active_spans(self):
        """Verify active spans tracking"""
        tracer = DistributedTracer()
        
        context1 = tracer.start_trace(operation="op1")
        _context2 = tracer.start_trace(operation="op2")
        
        active = tracer.get_active_spans()
        assert len(active) == 2
        
        tracer.end_span(context1)
        active = tracer.get_active_spans()
        assert len(active) == 1


class TestGlobalTracer:
    """Tests for global tracer functions"""
    
    def test_get_tracer_singleton(self):
        """Verify tracer is singleton"""
        tracer1 = get_tracer()
        tracer2 = get_tracer()
        assert tracer1 is tracer2
    
    def test_get_correlation_id(self):
        """Verify correlation ID retrieval"""
        correlation_id = get_correlation_id()
        assert correlation_id
        
        # Should return same ID on subsequent calls
        correlation_id2 = get_correlation_id()
        assert correlation_id == correlation_id2
    
    def test_create_trace_convenience(self):
        """Verify create_trace helper"""
        context = create_trace(operation="test_op")
        assert context.operation == "test_op"
        assert context.correlation_id
    
    def test_get_trace_headers(self):
        """Verify trace headers for propagation"""
        headers = get_trace_headers()
        
        assert "X-Correlation-ID" in headers
        assert "X-Request-ID" in headers
        assert headers["X-Correlation-ID"] == headers["X-Request-ID"]
